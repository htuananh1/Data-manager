# Telegram Coding AI Bot

Bot Telegram hỗ trợ lập trình viên trò chuyện bằng tiếng Việt, sử dụng mô hình `moonshotai/kimi-k2-thinking` thông qua AI Gateway.

## Tính năng chính
- **Hiểu ngữ cảnh**: lưu tối đa 16 lượt hội thoại gần nhất cho mỗi cuộc chat để duy trì lịch sử.
- **Nhiều API key**: luân phiên từng request qua danh sách khoá `AI_GATEWAY_API_KEYS`, đảm bảo bot không bị nghẽn khi một key chạm rate limit.
- **Theo dõi credit**: cấu hình `TOTAL_BUDGET_USD` (mặc định 5 USD); bot tự tính chi phí dựa trên giá `moonshotai/kimi-k2-thinking` (Input $0.60/M token, Output $2.50/M token, context 262K) và khoá bot khi chạm hạn mức.
- **Phản hồi nhanh**: sử dụng `aiogram` bất đồng bộ, hiển thị trạng thái typing và không chặn vòng lặp sự kiện khi gọi API.
- **Không bị nghẽn khi đông người dùng**: giới hạn song song bằng `asyncio.Semaphore` để kiểm soát tải nhưng vẫn xử lý nhiều request đồng thời.
- **Lệnh tiện dụng**: `/start` để khởi động, `/reset` để xoá lịch sử và giải phóng ngữ cảnh.
- **Chế độ giải bài tập chính xác**: `/code <đề bài>` yêu cầu bot giải bài tập lập trình từng bước, `/student <bài tập>` giải thích thân thiện như gia sư cho học sinh.
- **Gửi và nhận ảnh**: người dùng có thể gửi ảnh kèm chú thích, bot phản hồi lại ảnh đã nhận và đưa mô tả vào lịch sử để trợ lý AI xử lý theo bối cảnh.

## Chuẩn bị
1. Tạo bot và lấy `TELEGRAM_BOT_TOKEN` từ [@BotFather](https://t.me/botfather).
2. Chuẩn bị một hoặc nhiều khoá `AI_GATEWAY_API_KEY` từ AI Gateway (mỗi khoá cách nhau bởi dấu phẩy trong biến `AI_GATEWAY_API_KEYS`).
3. Sao chép file cấu hình mẫu và cập nhật biến môi trường:
   ```bash
   cp .env.example .env
   # chỉnh sửa .env bằng token thực tế
   ```

## Cài đặt và chạy bot
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

Bot sẽ bắt đầu poll Telegram và trả lời tin nhắn ngay khi có yêu cầu.

## Lệnh và chế độ hỗ trợ
- `/start`: reset cuộc trò chuyện và giới thiệu bot.
- `/reset`: xoá lịch sử đã lưu cho cuộc chat hiện tại.
- `/code <đề bài>`: yêu cầu bot giải bài tập lập trình với độ chính xác cao, có phân tích từng bước.
- `/student <mô tả bài>`: bật chế độ gia sư, giải thích dễ hiểu để học sinh nắm phương pháp.
- Gửi ảnh (photo) + chú thích: bot phản hồi lại ảnh đã nhận và đưa chú thích vào ngữ cảnh để trợ lý hiểu đúng yêu cầu.

## Cấu trúc chính
- `bot.py`: mã nguồn bot Telegram, bao gồm lưu lịch sử trò chuyện, pool API key và quản lý credit.
- `.env.example`: mẫu biến môi trường (`TELEGRAM_BOT_TOKEN`, `AI_GATEWAY_API_KEYS`, `TOTAL_BUDGET_USD`).
- `requirements.txt`: các thư viện cần thiết (`aiogram`, `openai`, `python-dotenv`).

Bạn có thể triển khai bot lên bất kỳ máy chủ nào hỗ trợ Python 3.10+ (Heroku, Railway, Fly.io, v.v.). Đảm bảo đặt biến môi trường giống nội dung `.env.example`, kiểm soát `TOTAL_BUDGET_USD` theo nhu cầu và bật tiến trình chạy `python bot.py`.
