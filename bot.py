import asyncio
import contextlib
import logging
import os
import tempfile
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional, Tuple

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AI_GATEWAY_API_KEYS = os.getenv("AI_GATEWAY_API_KEYS")
SINGLE_API_KEY = os.getenv("AI_GATEWAY_API_KEY")
TOTAL_BUDGET_USD = float(os.getenv("TOTAL_BUDGET_USD", "5"))

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing. Please set it in your environment.")

raw_keys = AI_GATEWAY_API_KEYS.split(",") if AI_GATEWAY_API_KEYS else []
api_keys = [key.strip() for key in raw_keys if key.strip()]

if not api_keys and SINGLE_API_KEY:
    api_keys = [SINGLE_API_KEY.strip()]

if not api_keys:
    raise RuntimeError(
        "AI_GATEWAY_API_KEYS or AI_GATEWAY_API_KEY is missing. Please set at least one API key in your environment."
    )

if TOTAL_BUDGET_USD <= 0:
    raise RuntimeError("TOTAL_BUDGET_USD must be greater than zero.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("chat-ai-bot")

BASE_URL = "https://ai-gateway.vercel.sh/v1"
REQUEST_SEMAPHORE = asyncio.Semaphore(8)
SYSTEM_MESSAGE = {
    "role": "system",
    "content": (
        "Bạn là trợ lý AI viết code, hỗ trợ người Việt rõ ràng, "
        "nhớ ngữ cảnh trò chuyện và trả lời súc tích."
    ),
}

CODE_SYSTEM_MESSAGE = (
    "Khi ở chế độ /code, hãy đóng vai chuyên gia lập trình. "
    "Đưa ra lời giải chính xác, từng bước rõ ràng và kiểm tra kỹ đầu ra."
)

STUDENT_SYSTEM_MESSAGE = (
    "Khi ở chế độ /student, hãy giải thích bài tập như gia sư tận tâm, "
    "đảm bảo học viên hiểu được phương pháp lẫn đáp án."
)


class BudgetExceededError(Exception):
    """Raised when the configured credit limit has been consumed."""


class OpenAIClientPool:
    def __init__(self, keys: List[str], base_url: str) -> None:
        if not keys:
            raise ValueError("At least one API key is required")
        self._clients = [OpenAI(api_key=key, base_url=base_url) for key in keys]
        self._lock = asyncio.Lock()
        self._index = 0

    async def acquire(self) -> OpenAI:
        async with self._lock:
            client = self._clients[self._index]
            self._index = (self._index + 1) % len(self._clients)
            return client


class BudgetManager:
    INPUT_COST_PER_TOKEN = 0.60 / 1_000_000  # USD per token
    OUTPUT_COST_PER_TOKEN = 2.50 / 1_000_000  # USD per token

    def __init__(self, total_budget: float) -> None:
        self._limit = total_budget
        self._spent = 0.0
        self._lock = asyncio.Lock()

    async def ensure_available(self) -> None:
        async with self._lock:
            if self._spent >= self._limit:
                raise BudgetExceededError

    async def register_usage(self, prompt_tokens: int, completion_tokens: int) -> Tuple[float, bool]:
        delta = (prompt_tokens * self.INPUT_COST_PER_TOKEN) + (
            completion_tokens * self.OUTPUT_COST_PER_TOKEN
        )
        async with self._lock:
            self._spent += delta
            remaining = max(self._limit - self._spent, 0.0)
            exhausted = self._spent >= self._limit
        return remaining, exhausted


class ConversationStore:
    def __init__(self, max_messages: int = 12) -> None:
        self._history: Dict[int, Deque[Dict[str, str]]] = defaultdict(lambda: deque(maxlen=max_messages))
        self._lock = asyncio.Lock()

    async def append(self, chat_id: int, role: str, content: str) -> None:
        async with self._lock:
            self._history[chat_id].append({"role": role, "content": content})

    async def clear(self, chat_id: int) -> None:
        async with self._lock:
            self._history.pop(chat_id, None)

    async def build_messages(self, chat_id: int, extra_system: Optional[str] = None) -> List[Dict[str, str]]:
        async with self._lock:
            history = list(self._history.get(chat_id, []))
        messages: List[Dict[str, str]] = [SYSTEM_MESSAGE]
        if extra_system:
            messages.append({"role": "system", "content": extra_system})
        messages.extend(history)
        return messages


client_pool = OpenAIClientPool(api_keys, BASE_URL)
budget_manager = BudgetManager(TOTAL_BUDGET_USD)
conversation_store = ConversationStore(max_messages=16)


def _run_completion(client: OpenAI, messages: List[Dict[str, str]]) -> Tuple[str, Optional[Dict[str, int]]]:
    response = client.chat.completions.create(
        model="moonshotai/kimi-k2-thinking",
        messages=messages,
    )
    choice = response.choices[0]
    content = choice.message.content.strip()
    usage = getattr(response, "usage", None)
    usage_dict: Optional[Dict[str, int]] = None
    if usage:
        usage_dict = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        }
    return content, usage_dict


async def generate_reply(
    chat_id: int,
    user_text: str,
    extra_system: Optional[str] = None,
) -> Tuple[str, Optional[float], bool]:
    await budget_manager.ensure_available()
    await conversation_store.append(chat_id, "user", user_text)
    payload = await conversation_store.build_messages(chat_id, extra_system)

    loop = asyncio.get_running_loop()
    async with REQUEST_SEMAPHORE:
        client = await client_pool.acquire()
        reply, usage = await loop.run_in_executor(None, _run_completion, client, payload)

    await conversation_store.append(chat_id, "assistant", reply)
    usage = usage or {}
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    remaining_credit, exhausted = await budget_manager.register_usage(prompt_tokens, completion_tokens)
    return reply, remaining_credit, exhausted


dp = Dispatcher()


async def _answer_with_ai(
    message: Message,
    user_text: str,
    extra_system: Optional[str] = None,
) -> None:
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        reply, remaining, exhausted = await generate_reply(message.chat.id, user_text, extra_system)
        if remaining is not None:
            reply = f"{reply}\n\n💰 Credit còn lại: ${remaining:.2f}"
        if exhausted:
            reply = (
                f"{reply}\n\n⚠️ Bot đã đạt giới hạn ngân sách ${TOTAL_BUDGET_USD:.2f}. "
                "Vui lòng bổ sung credit để tiếp tục."
            )
        await message.answer(reply)
    except BudgetExceededError:
        await message.answer(
            "Xin lỗi, bot đã hết hạn mức $5. Vui lòng cập nhật TOTAL_BUDGET_USD hoặc nạp thêm API credit."
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to generate reply: %s", exc)
        await message.answer("Xin lỗi, hiện tại mình không xử lý được yêu cầu. Vui lòng thử lại sau.")


def _extract_command_args(text: Optional[str]) -> str:
    if not text:
        return ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


@dp.message(CommandStart())
async def handle_start(message: Message) -> None:
    await conversation_store.clear(message.chat.id)
    await message.answer(
        "Xin chào! Tôi là bot AI hỗ trợ viết code. "
        "Hãy gửi yêu cầu hoặc sử dụng /reset để xoá lịch sử."
    )


@dp.message(Command("reset"))
async def handle_reset(message: Message) -> None:
    await conversation_store.clear(message.chat.id)
    await message.answer("Lịch sử đã được xoá, bạn có thể bắt đầu cuộc trò chuyện mới.")


@dp.message(Command("code"))
async def handle_code(message: Message) -> None:
    args = _extract_command_args(message.text)
    if not args:
        await message.answer("Vui lòng nhập đề bài sau /code, ví dụ: /code Viết hàm đảo chuỗi.")
        return
    prompt = (
        "[CHẾ ĐỘ GIẢI CODE]\n"
        f"Đề bài: {args}\n"
        "Yêu cầu lời giải từng bước, có kiểm thử nếu phù hợp."
    )
    await _answer_with_ai(message, prompt, CODE_SYSTEM_MESSAGE)


@dp.message(Command("student"))
async def handle_student(message: Message) -> None:
    args = _extract_command_args(message.text)
    if not args:
        await message.answer("Vui lòng mô tả bài tập sau /student để mình hướng dẫn chi tiết.")
        return
    prompt = (
        "[CHẾ ĐỘ GIA SƯ]\n"
        f"Nội dung bài tập: {args}\n"
        "Giải thích rõ ràng, chia thành bước dễ hiểu cho học sinh."
    )
    await _answer_with_ai(message, prompt, STUDENT_SYSTEM_MESSAGE)


@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    photo = message.photo[-1]
    caption = message.caption or ""
    file = await message.bot.get_file(photo.file_id)
    suffix = os.path.splitext(file.file_path or "")[-1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        await message.bot.download_file(file.file_path, tmp)
        temp_path = tmp.name
    try:
        preview = FSInputFile(temp_path)
        await message.answer_photo(
            preview,
            caption=(
                "Đã nhận ảnh của bạn 📷. Mình lưu lại ảnh trong lịch sử để tham chiếu "
                "và sẽ phản hồi dựa trên mô tả đi kèm."
            ),
        )
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.remove(temp_path)

    placeholder = caption.strip() or (
        "Người dùng vừa gửi một ảnh nhưng chưa có chú thích. Hãy nhắc họ mô tả chi tiết nội dung ảnh."
    )
    user_text = (
        "Người dùng đã gửi một ảnh qua Telegram. "
        f"Chú thích (nếu có): {caption or 'Chưa cung cấp.'}"
    )
    await _answer_with_ai(message, f"{user_text}\n\n{placeholder}")


@dp.message(F.text)
async def handle_prompt(message: Message) -> None:
    if not message.text:
        await message.answer("Mình chỉ có thể xử lý tin nhắn dạng văn bản.")
        return
    await _answer_with_ai(message, message.text)


async def main() -> None:
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
