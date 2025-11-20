import asyncio
import json
import logging
import os
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from dotenv import load_dotenv

load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("game-bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing. Please set it in your environment.")

# Data storage
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
PLAYERS_FILE = DATA_DIR / "players.json"

# Initialize bot
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)


# ==================== DATA MANAGEMENT ====================

class PlayerData:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.coins = 1000  # Starting coins
        self.level = 1
        self.exp = 0
        
        # Fishing game data
        self.fishing = {
            "rod_name": "Wooden Rod",  # Name of equipped rod
            "bait_count": 10,
            "caught_fish": [],
            "total_caught": 0,
            "last_fish_time": None,
        }
        
        # Pet system
        self.pets = {
            "owned": [],  # List of pet names owned
            "active": None,  # Currently active pet
            "pet_level": {},  # Pet levels: {pet_name: level}
        }
        
        # Dungeon game data
        self.dungeon = {
            "current_floor": 1,
            "max_floor": 1,
            "hp": 100,
            "max_hp": 100,
            "attack": 20,
            "defense": 10,
            "inventory": [],
            "equipped_weapon": None,
            "equipped_armor": None,
            "equipped_accessory": None,
        }
        
        # RNG game data
        self.rng = {
            "slots_played": 0,
            "dice_wins": 0,
            "jackpot_won": 0,
            "last_daily_bonus": None,
            "cards_opened": 0,
            "cards": [],  # List of card names owned
        }

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "coins": self.coins,
            "level": self.level,
            "exp": self.exp,
            "fishing": self.fishing,
            "pets": self.pets,
            "dungeon": self.dungeon,
            "rng": self.rng,
        }

    @classmethod
    def from_dict(cls, data: dict):
        player = cls(data["user_id"])
        player.coins = data.get("coins", 1000)
        player.level = data.get("level", 1)
        player.exp = data.get("exp", 0)
        player.fishing = data.get("fishing", player.fishing)
        player.pets = data.get("pets", player.pets)
        player.dungeon = data.get("dungeon", player.dungeon)
        player.rng = data.get("rng", player.rng)
        # Migration: convert rod_level to rod_name if needed
        if "rod_level" in player.fishing and "rod_name" not in player.fishing:
            rod_level = player.fishing["rod_level"]
            rod_names = ["Wooden Rod", "Bamboo Rod", "Iron Rod", "Steel Rod", "Titanium Rod"]
            player.fishing["rod_name"] = rod_names[min(rod_level - 1, len(rod_names) - 1)]
        return player


class DataManager:
    _players: Dict[int, PlayerData] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def load_players(cls):
        """Load players data from file"""
        async with cls._lock:
            if PLAYERS_FILE.exists():
                try:
                    with open(PLAYERS_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        cls._players = {
                            int(uid): PlayerData.from_dict(player_data)
                            for uid, player_data in data.items()
                        }
                    logger.info(f"Loaded {len(cls._players)} players")
                except Exception as e:
                    logger.error(f"Error loading players: {e}")
                    cls._players = {}
            else:
                cls._players = {}

    @classmethod
    async def save_players(cls):
        """Save players data to file"""
        async with cls._lock:
            try:
                data = {
                    str(uid): player.to_dict()
                    for uid, player in cls._players.items()
                }
                with open(PLAYERS_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                logger.info(f"Saved {len(cls._players)} players")
            except Exception as e:
                logger.error(f"Error saving players: {e}")

    @classmethod
    async def get_player(cls, user_id: int) -> PlayerData:
        """Get or create player"""
        async with cls._lock:
            if user_id not in cls._players:
                cls._players[user_id] = PlayerData(user_id)
                await cls.save_players()
            return cls._players[user_id]

    @classmethod
    async def save_player(cls, player: PlayerData):
        """Save single player"""
        async with cls._lock:
            cls._players[player.user_id] = player
            await cls.save_players()


# ==================== FISHING GAME ====================

try:
    from FishingData import FISH_TYPES, FISHING_RODS, PETS
except ImportError:
    # Fallback if FishingData not found
    FISH_TYPES = {
        "Cá rô": {"rarity": "common", "coins": 10, "exp": 5, "emoji": "🐟"},
    }
    FISHING_RODS = {
        "Wooden Rod": {"cost": 0, "tier": 1, "effects": {}, "catch_rates": {"common": 80, "uncommon": 15, "rare": 4, "epic": 0.9, "legendary": 0.1}, "description": "Cần câu cơ bản"},
    }
    PETS = {}


class FishingGame:
    @staticmethod
    def catch_fish(rod_name: str, pet_effects: Dict = None) -> Tuple[str, Dict]:
        """Catch a fish based on rod and pet effects"""
        rod = FISHING_RODS.get(rod_name, FISHING_RODS["Wooden Rod"])
        rates = rod["catch_rates"].copy()
        
        # Apply pet effects
        if pet_effects:
            if "increase_rare_rate" in pet_effects:
                # Increase rare/epic/legendary rates
                for rarity in ["rare", "epic", "legendary"]:
                    rates[rarity] *= (1 + pet_effects["increase_rare_rate"])
        
        # Normalize rates to 100%
        total = sum(rates.values())
        if total > 100:
            for key in rates:
                rates[key] = (rates[key] / total) * 100
        
        rand = random.random() * 100
        cumulative = 0
        
        for rarity in ["legendary", "epic", "rare", "uncommon", "common"]:
            cumulative += rates[rarity]
            if rand < cumulative:
                break
        
        # Select random fish of that rarity
        available_fish = [name for name, data in FISH_TYPES.items() if data["rarity"] == rarity]
        if not available_fish:
            # Fallback to common if no fish of that rarity
            available_fish = [name for name, data in FISH_TYPES.items() if data["rarity"] == "common"]
        
        fish_name = random.choice(available_fish)
        fish_data = FISH_TYPES[fish_name].copy()
        
        return fish_name, fish_data

    @staticmethod
    async def fish(player: PlayerData) -> str:
        """Perform fishing action"""
        if player.fishing["bait_count"] <= 0:
            return "❌ Bạn hết mồi rồi! Mua thêm mồi bằng /shop"
        
        rod_name = player.fishing.get("rod_name", "Wooden Rod")
        rod = FISHING_RODS.get(rod_name, FISHING_RODS["Wooden Rod"])
        
        # Check if reduce_bait effect applies
        bait_used = 1
        if "reduce_bait" in rod.get("effects", {}):
            if random.random() < rod["effects"]["reduce_bait"]:
                bait_used = 0
        
        player.fishing["bait_count"] -= bait_used
        
        # Get pet effects
        pet_effects = {}
        active_pet = player.pets.get("active")
        if active_pet and active_pet in PETS:
            pet_data = PETS[active_pet]
            pet_level = player.pets.get("pet_level", {}).get(active_pet, 1)
            # Pet effects scale with level
            for effect_name, effect_value in pet_data["effects"].items():
                pet_effects[effect_name] = effect_value * (1 + (pet_level - 1) * 0.1)
        
        fish_name, fish_data = FishingGame.catch_fish(rod_name, pet_effects)
        
        # Apply rod effects
        coins_earned = fish_data["coins"]
        exp_earned = fish_data["exp"]
        
        if "increase_coins" in rod.get("effects", {}):
            coins_earned = int(coins_earned * (1 + rod["effects"]["increase_coins"]))
        if "increase_exp" in rod.get("effects", {}):
            exp_earned = int(exp_earned * (1 + rod["effects"]["increase_exp"]))
        
        # Apply pet effects
        if "increase_coins" in pet_effects:
            coins_earned = int(coins_earned * (1 + pet_effects["increase_coins"]))
        if "increase_exp" in pet_effects:
            exp_earned = int(exp_earned * (1 + pet_effects["increase_exp"]))
        
        # Check double catch
        double_catch = False
        if "double_catch" in rod.get("effects", {}):
            if random.random() < rod["effects"]["double_catch"]:
                double_catch = True
        
        # Update player stats
        player.coins += coins_earned
        player.exp += exp_earned
        player.fishing["caught_fish"].append(fish_name)
        player.fishing["total_caught"] += 1
        player.fishing["last_fish_time"] = datetime.now().isoformat()
        
        result_text = (
            f"🎣 Bạn đã câu được: {fish_data['emoji']} **{fish_name}**\n"
            f"⚪ Độ hiếm: {fish_data['rarity'].upper()}\n"
            f"💰 +{coins_earned} coins\n"
            f"⭐ +{exp_earned} EXP\n"
        )
        
        if double_catch:
            # Catch second fish
            fish_name2, fish_data2 = FishingGame.catch_fish(rod_name, pet_effects)
            coins2 = fish_data2["coins"]
            exp2 = fish_data2["exp"]
            
            if "increase_coins" in rod.get("effects", {}):
                coins2 = int(coins2 * (1 + rod["effects"]["increase_coins"]))
            if "increase_exp" in rod.get("effects", {}):
                exp2 = int(exp2 * (1 + rod["effects"]["increase_exp"]))
            
            player.coins += coins2
            player.exp += exp2
            player.fishing["caught_fish"].append(fish_name2)
            player.fishing["total_caught"] += 1
            
            result_text += f"\n🎉 CÂU ĐÔI! {fish_data2['emoji']} **{fish_name2}**\n"
            result_text += f"💰 +{coins2} coins\n"
            result_text += f"⭐ +{exp2} EXP\n"
        
        result_text += f"🪝 Mồi còn lại: {player.fishing['bait_count']}"
        
        # Check level up
        exp_needed = player.level * 100
        if player.exp >= exp_needed:
            player.level += 1
            player.exp = 0
            player.coins += 100 * player.level
            result_text += f"\n\n🎉 LEVEL UP! Bạn đã lên cấp {player.level}! +{100 * player.level} coins"
        
        await DataManager.save_player(player)
        
        return result_text


# ==================== DUNGEON GAME ====================

MONSTERS = {
    1: [
        {"name": "Goblin", "hp": 30, "attack": 8, "coins": 20, "exp": 15},
        {"name": "Skeleton", "hp": 40, "attack": 10, "coins": 30, "exp": 20},
        {"name": "Orc", "hp": 50, "attack": 12, "coins": 40, "exp": 25},
    ],
    2: [
        {"name": "Dark Knight", "hp": 80, "attack": 18, "coins": 60, "exp": 40},
        {"name": "Shadow Beast", "hp": 100, "attack": 20, "coins": 80, "exp": 50},
        {"name": "Fire Demon", "hp": 120, "attack": 25, "coins": 100, "exp": 60},
    ],
    3: [
        {"name": "Dragon", "hp": 200, "attack": 35, "coins": 200, "exp": 100},
        {"name": "Lich King", "hp": 250, "attack": 40, "coins": 300, "exp": 150},
        {"name": "Ancient Guardian", "hp": 300, "attack": 45, "coins": 400, "exp": 200},
    ],
}

WEAPONS = {
    "Wooden Sword": {"attack": 5, "cost": 100, "rarity": "common"},
    "Iron Sword": {"attack": 15, "cost": 500, "rarity": "common"},
    "Steel Sword": {"attack": 30, "cost": 2000, "rarity": "uncommon"},
    "Mithril Blade": {"attack": 50, "cost": 5000, "rarity": "rare"},
    "Dragon Blade": {"attack": 60, "cost": 10000, "rarity": "epic"},
    "Excalibur": {"attack": 100, "cost": 50000, "rarity": "legendary"},
    "Demon Slayer": {"attack": 150, "cost": 100000, "rarity": "mythic"},
    "God Killer": {"attack": 250, "cost": 500000, "rarity": "divine"},
}

ARMOR = {
    "Leather Armor": {"defense": 5, "cost": 100, "rarity": "common"},
    "Iron Armor": {"defense": 15, "cost": 500, "rarity": "common"},
    "Steel Armor": {"defense": 30, "cost": 2000, "rarity": "uncommon"},
    "Mithril Armor": {"defense": 50, "cost": 5000, "rarity": "rare"},
    "Dragon Scale": {"defense": 60, "cost": 10000, "rarity": "epic"},
    "Phoenix Plate": {"defense": 100, "cost": 50000, "rarity": "legendary"},
    "Titanium Suit": {"defense": 150, "cost": 100000, "rarity": "mythic"},
    "Celestial Armor": {"defense": 250, "cost": 500000, "rarity": "divine"},
}

ACCESSORIES = {
    "Bronze Ring": {"attack": 2, "defense": 2, "cost": 200, "rarity": "common"},
    "Silver Ring": {"attack": 5, "defense": 5, "cost": 1000, "rarity": "uncommon"},
    "Gold Ring": {"attack": 10, "defense": 10, "cost": 5000, "rarity": "rare"},
    "Platinum Ring": {"attack": 20, "defense": 20, "cost": 20000, "rarity": "epic"},
    "Diamond Ring": {"attack": 40, "defense": 40, "cost": 100000, "rarity": "legendary"},
    "Amulet of Power": {"attack": 50, "defense": 30, "cost": 200000, "rarity": "mythic"},
    "Crown of Kings": {"attack": 100, "defense": 100, "cost": 1000000, "rarity": "divine"},
}

POTIONS = {
    "Health Potion": {"heal": 50, "cost": 50, "rarity": "common"},
    "Greater Health Potion": {"heal": 100, "cost": 200, "rarity": "uncommon"},
    "Super Health Potion": {"heal": 200, "cost": 500, "rarity": "rare"},
    "Elixir of Life": {"heal": 500, "cost": 2000, "rarity": "epic"},
    "Phoenix Tear": {"heal": 1000, "cost": 10000, "rarity": "legendary"},
}


class DungeonGame:
    @staticmethod
    async def explore(player: PlayerData) -> str:
        """Explore current dungeon floor"""
        floor = player.dungeon["current_floor"]
        
        if floor > 3:
            floor = 3  # Max floor for now
        
        monsters = MONSTERS[floor]
        monster = random.choice(monsters).copy()
        
        player_attack = player.dungeon["attack"]
        player_defense = player.dungeon["defense"]
        player_hp = player.dungeon["hp"]
        
        # Add weapon/armor/accessory stats
        if player.dungeon["equipped_weapon"]:
            weapon = WEAPONS.get(player.dungeon["equipped_weapon"], {})
            player_attack += weapon.get("attack", 0)
        if player.dungeon["equipped_armor"]:
            armor = ARMOR.get(player.dungeon["equipped_armor"], {})
            player_defense += armor.get("defense", 0)
        if player.dungeon.get("equipped_accessory"):
            accessory = ACCESSORIES.get(player.dungeon["equipped_accessory"], {})
            player_attack += accessory.get("attack", 0)
            player_defense += accessory.get("defense", 0)
        
        battle_log = []
        battle_log.append(f"⚔️ Bắt đầu chiến đấu với **{monster['name']}**!\n")
        
        monster_hp = monster["hp"]
        current_player_hp = player_hp
        
        # Battle loop
        turn = 1
        while monster_hp > 0 and current_player_hp > 0:
            # Player attack
            damage = max(1, player_attack - random.randint(0, 5))
            monster_hp -= damage
            battle_log.append(f"Turn {turn}: Bạn tấn công {monster['name']} -{damage} HP")
            
            if monster_hp <= 0:
                break
            
            # Monster attack
            monster_damage = max(1, monster["attack"] - player_defense + random.randint(-3, 3))
            current_player_hp -= monster_damage
            battle_log.append(f"        {monster['name']} tấn công bạn -{monster_damage} HP")
            
            turn += 1
            if turn > 20:  # Safety limit
                break
        
        if current_player_hp <= 0:
            # Player died
            player.dungeon["hp"] = player.dungeon["max_hp"]  # Respawn
            await DataManager.save_player(player)
            return (
                "💀 Bạn đã bị đánh bại!\n"
                f"**{monster['name']}** đã hạ gục bạn.\n"
                "Bạn đã hồi sinh với đầy HP."
            )
        
        # Victory!
        coins_earned = monster["coins"]
        exp_earned = monster["exp"]
        
        player.coins += coins_earned
        player.exp += exp_earned
        player.dungeon["hp"] = current_player_hp
        
        # Random loot
        loot = None
        if random.random() < 0.3:  # 30% chance
            loot_type = random.random()
            if loot_type < 0.4:  # 40% weapon
                loot = random.choice(list(WEAPONS.keys()))
            elif loot_type < 0.7:  # 30% armor
                loot = random.choice(list(ARMOR.keys()))
            elif loot_type < 0.9:  # 20% accessory
                loot = random.choice(list(ACCESSORIES.keys()))
            else:  # 10% potion
                loot = random.choice(list(POTIONS.keys()))
            
            if loot not in player.dungeon["inventory"]:
                player.dungeon["inventory"].append(loot)
        
        # Check level up
        exp_needed = player.level * 100
        if player.exp >= exp_needed:
            player.level += 1
            player.exp = 0
            player.coins += 100 * player.level
            player.dungeon["max_hp"] += 20
            player.dungeon["hp"] = player.dungeon["max_hp"]
            level_up_msg = f"\n\n🎉 LEVEL UP! Cấp {player.level}! +{100 * player.level} coins, +20 Max HP"
        else:
            level_up_msg = ""
        
        # Check floor progression
        if player.dungeon["current_floor"] < 3 and random.random() < 0.2:
            player.dungeon["current_floor"] += 1
            player.dungeon["max_floor"] = max(player.dungeon["max_floor"], player.dungeon["current_floor"])
            floor_msg = f"\n\n🏆 Bạn đã mở khóa tầng {player.dungeon['current_floor']}!"
        else:
            floor_msg = ""
        
        await DataManager.save_player(player)
        
        result = (
            f"✅ Chiến thắng!\n"
            f"💰 +{coins_earned} coins\n"
            f"⭐ +{exp_earned} EXP\n"
            f"❤️ HP còn lại: {current_player_hp}/{player.dungeon['max_hp']}"
        )
        
        if loot:
            result += f"\n🎁 Nhận được: **{loot}**"
        
        return result + level_up_msg + floor_msg


# ==================== RNG CARDS ====================

RNG_CARDS = {
    "Common Card": {"rarity": "common", "rate": 5000, "coins": 10, "emoji": "⚪"},
    "Uncommon Card": {"rarity": "uncommon", "rate": 2000, "coins": 50, "emoji": "🟢"},
    "Rare Card": {"rarity": "rare", "rate": 500, "coins": 200, "emoji": "🔵"},
    "Epic Card": {"rarity": "epic", "rate": 100, "coins": 1000, "emoji": "🟣"},
    "Legendary Card": {"rarity": "legendary", "rate": 20, "coins": 5000, "emoji": "🟡"},
    "Mythic Card": {"rarity": "mythic", "rate": 5, "coins": 20000, "emoji": "🔴"},
    "Divine Card": {"rarity": "divine", "rate": 1, "coins": 100000, "emoji": "✨"},
    "Ultra Rare Card": {"rarity": "ultra_rare", "rate": 0.1, "coins": 500000, "emoji": "💎"},
    "God Card": {"rarity": "god", "rate": 0.033, "coins": 2000000, "emoji": "👑"},
}

# Total rate = 10000 (for easier calculation)
# Ultra Rare: 1 in 100,000 (0.001%)
# God Card: 1 in 300,000 (0.00033%)


class CardSystem:
    @staticmethod
    def open_card() -> Tuple[str, Dict]:
        """Open a random card with ultra rare rates"""
        rand = random.random() * 100000  # Use 100000 for precision
        
        # Calculate cumulative rates
        if rand < 0.033:  # God Card: 1 in 300,000
            card_name = "God Card"
        elif rand < 0.133:  # Ultra Rare: 1 in 100,000
            card_name = "Ultra Rare Card"
        elif rand < 1.133:  # Divine: 1 in 10,000
            card_name = "Divine Card"
        elif rand < 6.133:  # Mythic: 1 in 2,000
            card_name = "Mythic Card"
        elif rand < 56.133:  # Legendary: 1 in 200
            card_name = "Legendary Card"
        elif rand < 156.133:  # Epic: 1 in 100
            card_name = "Epic Card"
        elif rand < 656.133:  # Rare: 1 in 20
            card_name = "Rare Card"
        elif rand < 2656.133:  # Uncommon: 1 in 5
            card_name = "Uncommon Card"
        else:  # Common: rest
            card_name = "Common Card"
        
        card_data = RNG_CARDS[card_name]
        return card_name, card_data

    @staticmethod
    async def open_card_pack(player: PlayerData, pack_count: int = 1) -> str:
        """Open card pack(s)"""
        cost_per_pack = 100
        total_cost = cost_per_pack * pack_count
        
        if player.coins < total_cost:
            return f"❌ Bạn không đủ coins! Cần {total_cost} coins để mở {pack_count} gói"
        
        player.coins -= total_cost
        player.rng["cards_opened"] += pack_count
        
        results = []
        total_coins_earned = 0
        
        for _ in range(pack_count):
            card_name, card_data = CardSystem.open_card()
            
            # Add to collection if not owned
            if card_name not in player.rng["cards"]:
                player.rng["cards"].append(card_name)
            
            coins_earned = card_data["coins"]
            total_coins_earned += coins_earned
            player.coins += coins_earned
            
            results.append({
                "name": card_name,
                "data": card_data,
                "coins": coins_earned,
            })
        
        await DataManager.save_player(player)
        
        # Format result
        text = f"🎴 **MỞ {pack_count} GÓI THẺ**\n\n"
        
        if pack_count == 1:
            card = results[0]
            text += (
                f"{card['data']['emoji']} **{card['name']}**\n"
                f"📊 Độ hiếm: {card['data']['rarity'].upper()}\n"
                f"💰 +{card['coins']} coins\n"
            )
        else:
            # Group by rarity
            by_rarity = {}
            for result in results:
                rarity = result['data']['rarity']
                if rarity not in by_rarity:
                    by_rarity[rarity] = []
                by_rarity[rarity].append(result)
            
            for rarity in ["god", "ultra_rare", "divine", "mythic", "legendary", "epic", "rare", "uncommon", "common"]:
                if rarity in by_rarity:
                    text += f"\n**{rarity.upper()}:**\n"
                    for result in by_rarity[rarity]:
                        text += f"  {result['data']['emoji']} {result['name']} (+{result['coins']} coins)\n"
        
        text += f"\n💰 Tổng nhận: {total_coins_earned} coins"
        text += f"\n💵 Coins hiện tại: {player.coins:,}"
        
        return text


# ==================== RNG GAME ====================

class RNGGame:
    @staticmethod
    async def slots(player: PlayerData, bet: int) -> str:
        """Play slots game"""
        if bet < 10:
            return "❌ Cược tối thiểu 10 coins!"
        if player.coins < bet:
            return "❌ Bạn không đủ coins!"
        
        player.coins -= bet
        player.rng["slots_played"] += 1
        
        # Generate 3 random symbols
        symbols = ["🍒", "🍋", "🍊", "🍇", "🔔", "⭐", "💎", "7️⃣"]
        result = [random.choice(symbols) for _ in range(3)]
        
        payout = 0
        multiplier = 0
        
        # Check for wins
        if result[0] == result[1] == result[2]:
            if result[0] == "💎":
                multiplier = 100  # Jackpot
            elif result[0] == "7️⃣":
                multiplier = 50
            elif result[0] == "⭐":
                multiplier = 20
            else:
                multiplier = 5
        elif result[0] == result[1] or result[1] == result[2]:
            multiplier = 2
        
        if multiplier > 0:
            payout = bet * multiplier
            player.coins += payout
            if multiplier >= 50:
                player.rng["jackpot_won"] += 1
        
        await DataManager.save_player(player)
        
        slot_display = " | ".join(result)
        
        if payout > 0:
            return (
                f"🎰 SLOTS\n"
                f"{slot_display}\n\n"
                f"🎉 THẮNG! x{multiplier}\n"
                f"💰 Cược: {bet} → Nhận: {payout} coins\n"
                f"💵 Tổng coins: {player.coins}"
            )
        else:
            return (
                f"🎰 SLOTS\n"
                f"{slot_display}\n\n"
                f"❌ Thua\n"
                f"💰 Mất: {bet} coins\n"
                f"💵 Còn lại: {player.coins} coins"
            )

    @staticmethod
    async def dice(player: PlayerData, bet: int, guess: int) -> str:
        """Play dice game"""
        if bet < 10:
            return "❌ Cược tối thiểu 10 coins!"
        if player.coins < bet:
            return "❌ Bạn không đủ coins!"
        if guess < 1 or guess > 6:
            return "❌ Đoán số từ 1-6!"
        
        player.coins -= bet
        dice_roll = random.randint(1, 6)
        
        if dice_roll == guess:
            payout = bet * 6
            player.coins += payout
            player.rng["dice_wins"] += 1
            await DataManager.save_player(player)
            return (
                f"🎲 XÚC XẮC\n"
                f"🎲 Kết quả: {dice_roll}\n"
                f"🎯 Bạn đoán: {guess}\n\n"
                f"🎉 ĐÚNG! x6\n"
                f"💰 Cược: {bet} → Nhận: {payout} coins\n"
                f"💵 Tổng coins: {player.coins}"
            )
        else:
            await DataManager.save_player(player)
            return (
                f"🎲 XÚC XẮC\n"
                f"🎲 Kết quả: {dice_roll}\n"
                f"🎯 Bạn đoán: {guess}\n\n"
                f"❌ SAI\n"
                f"💰 Mất: {bet} coins\n"
                f"💵 Còn lại: {player.coins} coins"
            )

    @staticmethod
    async def daily_bonus(player: PlayerData) -> str:
        """Daily bonus"""
        now = datetime.now()
        last_bonus = player.rng.get("last_daily_bonus")
        
        if last_bonus:
            last_date = datetime.fromisoformat(last_bonus)
            if (now - last_date).days < 1:
                next_bonus = last_date + timedelta(days=1)
                hours_left = (next_bonus - now).seconds // 3600
                return f"⏰ Bạn đã nhận bonus hôm nay rồi! Quay lại sau {hours_left} giờ."
        
        bonus = random.randint(50, 200) + (player.level * 10)
        player.coins += bonus
        player.rng["last_daily_bonus"] = now.isoformat()
        await DataManager.save_player(player)
        
        return (
            f"🎁 BONUS HÀNG NGÀY\n"
            f"💰 Nhận được: {bonus} coins\n"
            f"💵 Tổng coins: {player.coins}\n"
            f"⏰ Quay lại sau 24h để nhận tiếp!"
        )


# ==================== KEYBOARDS ====================

def main_menu_keyboard():
    """Main menu keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎣 Câu Cá", callback_data="game_fishing"),
            InlineKeyboardButton(text="⚔️ Hầm Ngục", callback_data="game_dungeon"),
        ],
        [
            InlineKeyboardButton(text="🎰 RNG Games", callback_data="game_rng"),
            InlineKeyboardButton(text="👤 Profile", callback_data="profile"),
        ],
        [
            InlineKeyboardButton(text="🛒 Shop", callback_data="shop"),
            InlineKeyboardButton(text="📊 Stats", callback_data="stats"),
        ],
    ])
    return keyboard


def fishing_keyboard():
    """Fishing game keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎣 Câu Cá", callback_data="fish_catch")],
        [InlineKeyboardButton(text="🪝 Mua Mồi (10 coins/mồi)", callback_data="fish_buy_bait")],
        [InlineKeyboardButton(text="🪝 Mua Cần Câu", callback_data="fish_upgrade_rod")],
        [InlineKeyboardButton(text="🐾 Pet", callback_data="fish_pet")],
        [InlineKeyboardButton(text="📋 Xem Cá Đã Câu", callback_data="fish_inventory")],
        [InlineKeyboardButton(text="🔙 Menu Chính", callback_data="main_menu")],
    ])
    return keyboard


def dungeon_keyboard():
    """Dungeon game keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Khám Phá", callback_data="dungeon_explore")],
        [InlineKeyboardButton(text="💊 Hồi HP (50 coins)", callback_data="dungeon_heal")],
        [InlineKeyboardButton(text="🎒 Inventory", callback_data="dungeon_inventory")],
        [InlineKeyboardButton(text="🔙 Menu Chính", callback_data="main_menu")],
    ])
    return keyboard


def rng_keyboard():
    """RNG game keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎴 Mở Thẻ (100 coins/gói)", callback_data="rng_open_card")],
        [InlineKeyboardButton(text="🎰 Slots (cược 10+)", callback_data="rng_slots")],
        [InlineKeyboardButton(text="🎲 Dice (cược 10+)", callback_data="rng_dice")],
        [InlineKeyboardButton(text="🎁 Daily Bonus", callback_data="rng_daily")],
        [InlineKeyboardButton(text="📚 Bộ Sưu Tập Thẻ", callback_data="rng_collection")],
        [InlineKeyboardButton(text="🔙 Menu Chính", callback_data="main_menu")],
    ])
    return keyboard


# ==================== COMMAND HANDLERS ====================

@router.message(CommandStart())
async def cmd_start(message: Message):
    """Start command"""
    player = await DataManager.get_player(message.from_user.id)
    
    welcome = (
        f"🎮 **CHÀO MỪNG ĐẾN GAME BOT!**\n\n"
        f"👤 **{message.from_user.first_name}**\n"
        f"💰 Coins: {player.coins}\n"
        f"⭐ Level: {player.level}\n"
        f"📊 EXP: {player.exp}/{player.level * 100}\n\n"
        f"Chọn game để bắt đầu:"
    )
    
    await message.answer(welcome, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    """Menu command"""
    await message.answer("📋 **MENU CHÍNH**", reply_markup=main_menu_keyboard(), parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Help command - show all commands"""
    help_text = (
        "📚 **DANH SÁCH LỆNH**\n\n"
        "**Lệnh chính:**\n"
        "/start - Bắt đầu game\n"
        "/menu - Mở menu chính\n"
        "/help - Xem danh sách lệnh này\n"
        "/profile - Xem thông tin người chơi\n"
        "/stats - Xem thống kê\n\n"
        "**Game Câu Cá:**\n"
        "Sử dụng menu hoặc nút trong bot\n\n"
        "**Game Hầm Ngục:**\n"
        "Sử dụng menu hoặc nút trong bot\n\n"
        "**RNG Games:**\n"
        "/slots <số coins> - Chơi slots\n"
        "/dice <cược> <số 1-6> - Chơi xúc xắc\n"
        "/card - Mở 1 gói thẻ (100 coins)\n"
        "/card <số> - Mở nhiều gói thẻ\n\n"
        "**Shop:**\n"
        "/shop - Xem cửa hàng\n"
        "/buy <tên vật phẩm> - Mua vật phẩm\n\n"
        "**Vật phẩm có thể mua:**\n"
        "- Vũ khí: Wooden Sword, Iron Sword, Steel Sword, Mithril Blade, Dragon Blade, Excalibur, Demon Slayer, God Killer\n"
        "- Giáp: Leather Armor, Iron Armor, Steel Armor, Mithril Armor, Dragon Scale, Phoenix Plate, Titanium Suit, Celestial Armor\n"
        "- Phụ kiện: Bronze Ring, Silver Ring, Gold Ring, Platinum Ring, Diamond Ring, Amulet of Power, Crown of Kings\n"
        "- Thuốc: Health Potion, Greater Health Potion, Super Health Potion, Elixir of Life, Phoenix Tear\n"
        "- Cần câu: Cần câu Cấp 2-5\n\n"
        "**Thẻ RNG:**\n"
        "Tỷ lệ thẻ:\n"
        "⚪ Common: ~50%\n"
        "🟢 Uncommon: ~20%\n"
        "🔵 Rare: ~5%\n"
        "🟣 Epic: ~1%\n"
        "🟡 Legendary: ~0.2%\n"
        "🔴 Mythic: ~0.05%\n"
        "✨ Divine: ~0.01%\n"
        "💎 Ultra Rare: 1/100,000 (0.001%)\n"
        "👑 God Card: 1/300,000 (0.00033%)\n\n"
        "Chúc bạn chơi vui vẻ! 🎮"
    )
    await message.answer(help_text, parse_mode="Markdown")


# ==================== CALLBACK HANDLERS ====================

@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    """Return to main menu"""
    await callback.message.edit_text("📋 **MENU CHÍNH**", reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "game_fishing")
async def callback_fishing_menu(callback: CallbackQuery):
    """Fishing game menu"""
    player = await DataManager.get_player(callback.from_user.id)
    rod_name = player.fishing.get("rod_name", "Wooden Rod")
    active_pet = player.pets.get("active", "Không có")
    
    text = (
        f"🎣 **GAME CÂU CÁ**\n\n"
        f"🪝 Cần câu: {rod_name}\n"
        f"🪝 Mồi: {player.fishing['bait_count']}\n"
        f"🐟 Tổng cá đã câu: {player.fishing['total_caught']}\n"
        f"🐾 Pet: {active_pet}\n\n"
        f"Chọn hành động:"
    )
    
    await callback.message.edit_text(text, reply_markup=fishing_keyboard(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "fish_catch")
async def callback_fish_catch(callback: CallbackQuery):
    """Catch fish"""
    player = await DataManager.get_player(callback.from_user.id)
    result = await FishingGame.fish(player)
    
    await callback.message.edit_text(result, reply_markup=fishing_keyboard(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "fish_buy_bait")
async def callback_buy_bait(callback: CallbackQuery):
    """Buy bait"""
    player = await DataManager.get_player(callback.from_user.id)
    
    if player.coins < 10:
        await callback.answer("❌ Bạn không đủ coins! (Cần 10 coins/mồi)", show_alert=True)
        return
    
    player.coins -= 10
    player.fishing["bait_count"] += 1
    await DataManager.save_player(player)
    
    await callback.answer(f"✅ Đã mua 1 mồi! Còn {player.fishing['bait_count']} mồi")
    
    # Refresh menu
    text = (
        f"🎣 **GAME CÂU CÁ**\n\n"
        f"🪝 Cần câu: Cấp {player.fishing['rod_level']}\n"
        f"🪝 Mồi: {player.fishing['bait_count']}\n"
        f"🐟 Tổng cá đã câu: {player.fishing['total_caught']}\n\n"
        f"Chọn hành động:"
    )
    await callback.message.edit_text(text, reply_markup=fishing_keyboard(), parse_mode="Markdown")


@router.callback_query(F.data == "fish_upgrade_rod")
async def callback_upgrade_rod(callback: CallbackQuery):
    """Show rod shop"""
    player = await DataManager.get_player(callback.from_user.id)
    current_rod = player.fishing.get("rod_name", "Wooden Rod")
    
    text = "🪝 **CỬA HÀNG CẦN CÂU**\n\n"
    text += f"Cần câu hiện tại: {current_rod}\n\n"
    
    # Show available rods (next 10 rods)
    rod_list = list(FISHING_RODS.keys())
    try:
        current_index = rod_list.index(current_rod)
    except ValueError:
        current_index = 0
    
    # Show next 10 rods
    for i in range(current_index + 1, min(current_index + 11, len(rod_list))):
        rod_name = rod_list[i]
        rod_data = FISHING_RODS[rod_name]
        owned = "✅" if rod_name == current_rod else ""
        text += f"{owned} {rod_name}: {rod_data['cost']:,} coins\n"
        text += f"   {rod_data['description']}\n\n"
    
    text += "Sử dụng /buy <tên cần câu> để mua"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Câu Cá", callback_data="game_fishing")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "fish_inventory")
async def callback_fish_inventory(callback: CallbackQuery):
    """View caught fish"""
    player = await DataManager.get_player(callback.from_user.id)
    
    if not player.fishing["caught_fish"]:
        text = "📋 Bạn chưa câu được con cá nào!"
    else:
        # Count fish
        fish_count = {}
        for fish in player.fishing["caught_fish"][-20:]:  # Last 20
            if fish in FISH_TYPES:
                fish_count[fish] = fish_count.get(fish, 0) + 1
        
        text = "📋 **CÁ ĐÃ CÂU** (20 gần nhất):\n\n"
        for fish, count in fish_count.items():
            fish_data = FISH_TYPES[fish]
            text += f"{fish_data['emoji']} {fish}: {count}x\n"
    
    await callback.message.edit_text(text, reply_markup=fishing_keyboard(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "fish_pet")
async def callback_fish_pet(callback: CallbackQuery):
    """Pet management"""
    player = await DataManager.get_player(callback.from_user.id)
    active_pet = player.pets.get("active")
    
    text = "🐾 **QUẢN LÝ PET**\n\n"
    text += f"Pet đang dùng: {active_pet if active_pet else 'Không có'}\n\n"
    text += "**Pet sở hữu:**\n"
    
    if not player.pets.get("owned"):
        text += "Bạn chưa có pet nào!\n\n"
    else:
        for pet_name in player.pets["owned"]:
            if pet_name in PETS:
                pet_data = PETS[pet_name]
                pet_level = player.pets.get("pet_level", {}).get(pet_name, 1)
                active = "✅" if pet_name == active_pet else ""
                text += f"{active} {pet_data['emoji']} {pet_name} (Cấp {pet_level})\n"
                text += f"   {pet_data['description']}\n\n"
    
    text += "**Pet có thể mua:**\n"
    for pet_name, pet_data in PETS.items():
        owned = "✅" if pet_name in player.pets.get("owned", []) else ""
        text += f"{owned} {pet_data['emoji']} {pet_name}: {pet_data['cost']:,} coins\n"
        text += f"   {pet_data['description']}\n\n"
    
    text += "Sử dụng /buy <tên pet> để mua\n"
    text += "Sử dụng /pet <tên pet> để kích hoạt"
    
    keyboard_buttons = []
    for pet_name in player.pets.get("owned", []):
        if pet_name != active_pet:
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"🐾 Kích hoạt {pet_name}",
                callback_data=f"activate_pet_{pet_name}"
            )])
    
    keyboard_buttons.append([InlineKeyboardButton(text="🔙 Câu Cá", callback_data="game_fishing")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("activate_pet_"))
async def callback_activate_pet(callback: CallbackQuery):
    """Activate pet"""
    pet_name = callback.data.replace("activate_pet_", "")
    player = await DataManager.get_player(callback.from_user.id)
    
    if pet_name not in player.pets.get("owned", []):
        await callback.answer("❌ Bạn chưa sở hữu pet này!", show_alert=True)
        return
    
    player.pets["active"] = pet_name
    await DataManager.save_player(player)
    await callback.answer(f"✅ Đã kích hoạt {pet_name}!")
    await callback_fish_pet(callback)


@router.callback_query(F.data == "game_dungeon")
async def callback_dungeon_menu(callback: CallbackQuery):
    """Dungeon game menu"""
    player = await DataManager.get_player(callback.from_user.id)
    
    text = (
        f"⚔️ **HẦM NGỤC**\n\n"
        f"🏰 Tầng hiện tại: {player.dungeon['current_floor']}\n"
        f"🏆 Tầng cao nhất: {player.dungeon['max_floor']}\n"
        f"❤️ HP: {player.dungeon['hp']}/{player.dungeon['max_hp']}\n"
        f"⚔️ Tấn công: {player.dungeon['attack']}\n"
        f"🛡️ Phòng thủ: {player.dungeon['defense']}\n\n"
        f"Chọn hành động:"
    )
    
    await callback.message.edit_text(text, reply_markup=dungeon_keyboard(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "dungeon_explore")
async def callback_dungeon_explore(callback: CallbackQuery):
    """Explore dungeon"""
    player = await DataManager.get_player(callback.from_user.id)
    result = await DungeonGame.explore(player)
    
    await callback.message.edit_text(result, reply_markup=dungeon_keyboard(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "dungeon_heal")
async def callback_dungeon_heal(callback: CallbackQuery):
    """Heal in dungeon"""
    player = await DataManager.get_player(callback.from_user.id)
    
    if player.dungeon["hp"] >= player.dungeon["max_hp"]:
        await callback.answer("✅ HP đã đầy rồi!", show_alert=True)
        return
    
    if player.coins < 50:
        await callback.answer("❌ Bạn không đủ coins! Cần 50 coins", show_alert=True)
        return
    
    player.coins -= 50
    player.dungeon["hp"] = player.dungeon["max_hp"]
    await DataManager.save_player(player)
    
    await callback.answer("✅ Đã hồi đầy HP!")
    
    # Refresh menu
    text = (
        f"⚔️ **HẦM NGỤC**\n\n"
        f"🏰 Tầng hiện tại: {player.dungeon['current_floor']}\n"
        f"🏆 Tầng cao nhất: {player.dungeon['max_floor']}\n"
        f"❤️ HP: {player.dungeon['hp']}/{player.dungeon['max_hp']}\n"
        f"⚔️ Tấn công: {player.dungeon['attack']}\n"
        f"🛡️ Phòng thủ: {player.dungeon['defense']}\n\n"
        f"Chọn hành động:"
    )
    await callback.message.edit_text(text, reply_markup=dungeon_keyboard(), parse_mode="Markdown")


@router.callback_query(F.data == "dungeon_inventory")
async def callback_dungeon_inventory(callback: CallbackQuery):
    """View dungeon inventory"""
    player = await DataManager.get_player(callback.from_user.id)
    
    text = "🎒 **INVENTORY**\n\n"
    
    if not player.dungeon["inventory"]:
        text += "Trống!"
    else:
        for item in player.dungeon["inventory"]:
            equipped = ""
            if item == player.dungeon.get("equipped_weapon"):
                equipped = " ⚔️ (Đang dùng)"
            elif item == player.dungeon.get("equipped_armor"):
                equipped = " 🛡️ (Đang dùng)"
            
            if item in WEAPONS:
                stats = WEAPONS[item]
                text += f"⚔️ {item} (+{stats['attack']} ATK){equipped}\n"
            elif item in ARMOR:
                stats = ARMOR[item]
                text += f"🛡️ {item} (+{stats['defense']} DEF){equipped}\n"
            elif item in ACCESSORIES:
                stats = ACCESSORIES[item]
                text += f"💍 {item} (+{stats['attack']} ATK, +{stats['defense']} DEF){equipped}\n"
            elif item in POTIONS:
                stats = POTIONS[item]
                text += f"🧪 {item} (Hồi {stats['heal']} HP)\n"
    
    # Add equip buttons
    keyboard_buttons = []
    for item in player.dungeon["inventory"][:10]:  # Max 10 items
        if item in WEAPONS and item != player.dungeon.get("equipped_weapon"):
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"⚔️ Trang bị {item}",
                callback_data=f"equip_weapon_{item}"
            )])
        elif item in ARMOR and item != player.dungeon.get("equipped_armor"):
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"🛡️ Trang bị {item}",
                callback_data=f"equip_armor_{item}"
            )])
        elif item in ACCESSORIES and item != player.dungeon.get("equipped_accessory"):
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"💍 Trang bị {item}",
                callback_data=f"equip_accessory_{item}"
            )])
        elif item in POTIONS:
            keyboard_buttons.append([InlineKeyboardButton(
                text=f"🧪 Dùng {item}",
                callback_data=f"use_potion_{item}"
            )])
    
    keyboard_buttons.append([InlineKeyboardButton(text="🔙 Hầm Ngục", callback_data="game_dungeon")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("equip_weapon_"))
async def callback_equip_weapon(callback: CallbackQuery):
    """Equip weapon"""
    item = callback.data.replace("equip_weapon_", "")
    player = await DataManager.get_player(callback.from_user.id)
    
    if item not in player.dungeon["inventory"]:
        await callback.answer("❌ Vật phẩm không tồn tại!", show_alert=True)
        return
    
    player.dungeon["equipped_weapon"] = item
    await DataManager.save_player(player)
    await callback.answer(f"✅ Đã trang bị {item}!")
    await callback_dungeon_inventory(callback)


@router.callback_query(F.data.startswith("equip_armor_"))
async def callback_equip_armor(callback: CallbackQuery):
    """Equip armor"""
    item = callback.data.replace("equip_armor_", "")
    player = await DataManager.get_player(callback.from_user.id)
    
    if item not in player.dungeon["inventory"]:
        await callback.answer("❌ Vật phẩm không tồn tại!", show_alert=True)
        return
    
    player.dungeon["equipped_armor"] = item
    await DataManager.save_player(player)
    await callback.answer(f"✅ Đã trang bị {item}!")
    await callback_dungeon_inventory(callback)


@router.callback_query(F.data.startswith("equip_accessory_"))
async def callback_equip_accessory(callback: CallbackQuery):
    """Equip accessory"""
    item = callback.data.replace("equip_accessory_", "")
    player = await DataManager.get_player(callback.from_user.id)
    
    if item not in player.dungeon["inventory"]:
        await callback.answer("❌ Vật phẩm không tồn tại!", show_alert=True)
        return
    
    player.dungeon["equipped_accessory"] = item
    await DataManager.save_player(player)
    await callback.answer(f"✅ Đã trang bị {item}!")
    await callback_dungeon_inventory(callback)


@router.callback_query(F.data.startswith("use_potion_"))
async def callback_use_potion(callback: CallbackQuery):
    """Use potion"""
    item = callback.data.replace("use_potion_", "")
    player = await DataManager.get_player(callback.from_user.id)
    
    if item not in player.dungeon["inventory"]:
        await callback.answer("❌ Vật phẩm không tồn tại!", show_alert=True)
        return
    
    if item not in POTIONS:
        await callback.answer("❌ Đây không phải thuốc!", show_alert=True)
        return
    
    if player.dungeon["hp"] >= player.dungeon["max_hp"]:
        await callback.answer("✅ HP đã đầy rồi!", show_alert=True)
        return
    
    potion = POTIONS[item]
    heal_amount = potion["heal"]
    new_hp = min(player.dungeon["hp"] + heal_amount, player.dungeon["max_hp"])
    healed = new_hp - player.dungeon["hp"]
    
    player.dungeon["hp"] = new_hp
    player.dungeon["inventory"].remove(item)  # Consume potion
    await DataManager.save_player(player)
    
    await callback.answer(f"✅ Đã hồi {healed} HP!")
    await callback_dungeon_inventory(callback)


@router.callback_query(F.data == "game_rng")
async def callback_rng_menu(callback: CallbackQuery):
    """RNG game menu"""
    player = await DataManager.get_player(callback.from_user.id)
    
    text = (
        f"🎰 **RNG GAMES**\n\n"
        f"💰 Coins: {player.coins}\n"
        f"🎰 Slots đã chơi: {player.rng['slots_played']}\n"
        f"🎲 Dice thắng: {player.rng['dice_wins']}\n"
        f"✨ Jackpot: {player.rng['jackpot_won']}\n\n"
        f"Chọn game:"
    )
    
    await callback.message.edit_text(text, reply_markup=rng_keyboard(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "rng_slots")
async def callback_rng_slots(callback: CallbackQuery):
    """Play slots - ask for bet"""
    await callback.message.edit_text(
        "🎰 **SLOTS**\n\nNhập số coins muốn cược (tối thiểu 10):\nVí dụ: /slots 50",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 RNG Games", callback_data="game_rng")]
        ])
    )
    await callback.answer("Nhập /slots <số coins> để chơi")


@router.message(Command("slots"))
async def cmd_slots(message: Message):
    """Slots command"""
    try:
        bet = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("❌ Sử dụng: /slots <số coins>\nVí dụ: /slots 50")
        return
    
    player = await DataManager.get_player(message.from_user.id)
    result = await RNGGame.slots(player, bet)
    await message.answer(result, parse_mode="Markdown")


@router.callback_query(F.data == "rng_dice")
async def callback_rng_dice(callback: CallbackQuery):
    """Play dice - ask for bet and guess"""
    await callback.message.edit_text(
        "🎲 **DICE**\n\nNhập: /dice <cược> <số đoán 1-6>\nVí dụ: /dice 100 3",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 RNG Games", callback_data="game_rng")]
        ])
    )
    await callback.answer("Nhập /dice <cược> <số> để chơi")


@router.message(Command("dice"))
async def cmd_dice(message: Message):
    """Dice command"""
    try:
        parts = message.text.split()
        bet = int(parts[1])
        guess = int(parts[2])
    except (IndexError, ValueError):
        await message.answer("❌ Sử dụng: /dice <cược> <số đoán 1-6>\nVí dụ: /dice 100 3")
        return
    
    player = await DataManager.get_player(message.from_user.id)
    result = await RNGGame.dice(player, bet, guess)
    await message.answer(result, parse_mode="Markdown")


@router.callback_query(F.data == "rng_daily")
async def callback_rng_daily(callback: CallbackQuery):
    """Daily bonus"""
    player = await DataManager.get_player(callback.from_user.id)
    result = await RNGGame.daily_bonus(player)
    await callback.message.edit_text(result, reply_markup=rng_keyboard(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "rng_open_card")
async def callback_rng_open_card(callback: CallbackQuery):
    """Open card - ask for count"""
    await callback.message.edit_text(
        "🎴 **MỞ THẺ RNG**\n\nNhập số gói muốn mở (100 coins/gói):\nVí dụ: /card 1 hoặc /card 10",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 RNG Games", callback_data="game_rng")]
        ])
    )
    await callback.answer("Nhập /card <số> để mở thẻ")


@router.message(Command("card"))
async def cmd_card(message: Message):
    """Open card pack command"""
    try:
        pack_count = int(message.text.split()[1]) if len(message.text.split()) > 1 else 1
        if pack_count < 1 or pack_count > 100:
            await message.answer("❌ Số gói phải từ 1-100!")
            return
    except (IndexError, ValueError):
        pack_count = 1
    
    player = await DataManager.get_player(message.from_user.id)
    result = await CardSystem.open_card_pack(player, pack_count)
    await message.answer(result, parse_mode="Markdown")


@router.message(Command("pet"))
async def cmd_pet(message: Message):
    """Activate pet command"""
    try:
        pet_name = " ".join(message.text.split()[1:])
    except IndexError:
        await message.answer("❌ Sử dụng: /pet <tên pet>\nVí dụ: /pet Cá vàng")
        return
    
    player = await DataManager.get_player(message.from_user.id)
    
    if pet_name not in player.pets.get("owned", []):
        await message.answer(f"❌ Bạn chưa sở hữu pet {pet_name}!")
        return
    
    player.pets["active"] = pet_name
    await DataManager.save_player(player)
    
    pet_data = PETS.get(pet_name, {})
    await message.answer(
        f"✅ Đã kích hoạt {pet_data.get('emoji', '🐾')} **{pet_name}**!\n"
        f"{pet_data.get('description', '')}"
    )


@router.callback_query(F.data == "rng_collection")
async def callback_rng_collection(callback: CallbackQuery):
    """View card collection"""
    player = await DataManager.get_player(callback.from_user.id)
    
    text = "📚 **BỘ SƯU TẬP THẺ**\n\n"
    text += f"🎴 Tổng thẻ đã mở: {player.rng['cards_opened']}\n"
    text += f"📦 Thẻ sở hữu: {len(player.rng['cards'])}/{len(RNG_CARDS)}\n\n"
    
    if not player.rng["cards"]:
        text += "Bạn chưa có thẻ nào!"
    else:
        # Group by rarity
        by_rarity = {}
        for card_name in player.rng["cards"]:
            if card_name in RNG_CARDS:
                rarity = RNG_CARDS[card_name]["rarity"]
                if rarity not in by_rarity:
                    by_rarity[rarity] = []
                by_rarity[rarity].append(card_name)
        
        rarity_order = ["god", "ultra_rare", "divine", "mythic", "legendary", "epic", "rare", "uncommon", "common"]
        for rarity in rarity_order:
            if rarity in by_rarity:
                text += f"**{rarity.upper()}:**\n"
                for card_name in by_rarity[rarity]:
                    card_data = RNG_CARDS[card_name]
                    text += f"  {card_data['emoji']} {card_name}\n"
                text += "\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 RNG Games", callback_data="game_rng")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "profile")
async def callback_profile(callback: CallbackQuery):
    """View profile"""
    player = await DataManager.get_player(callback.from_user.id)
    
    text = (
        f"👤 **PROFILE**\n\n"
        f"💰 Coins: {player.coins:,}\n"
        f"⭐ Level: {player.level}\n"
        f"📊 EXP: {player.exp}/{player.level * 100}\n\n"
        f"🎣 **Câu Cá:**\n"
        f"  🪝 Cần câu: Cấp {player.fishing['rod_level']}\n"
        f"  🐟 Đã câu: {player.fishing['total_caught']} con\n\n"
        f"⚔️ **Hầm Ngục:**\n"
        f"  🏆 Tầng cao nhất: {player.dungeon['max_floor']}\n"
        f"  ❤️ HP: {player.dungeon['hp']}/{player.dungeon['max_hp']}\n\n"
        f"🎰 **RNG:**\n"
        f"  🎰 Slots: {player.rng['slots_played']} lần\n"
        f"  🎲 Dice thắng: {player.rng['dice_wins']}\n"
        f"  ✨ Jackpot: {player.rng['jackpot_won']}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Menu Chính", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "shop")
async def callback_shop(callback: CallbackQuery):
    """Shop menu"""
    player = await DataManager.get_player(callback.from_user.id)
    
    text = (
        f"🛒 **SHOP**\n\n"
        f"💰 Coins của bạn: {player.coins:,}\n\n"
        f"**⚔️ Vũ khí:**\n"
    )
    
    for name, stats in WEAPONS.items():
        owned = "✅" if name in player.dungeon["inventory"] else ""
        rarity_emoji = {"common": "⚪", "uncommon": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟡", "mythic": "🔴", "divine": "✨"}
        rarity = rarity_emoji.get(stats.get("rarity", "common"), "")
        text += f"{owned} {rarity} ⚔️ {name}: +{stats['attack']} ATK - {stats['cost']:,} coins\n"
    
    text += f"\n**🛡️ Giáp:**\n"
    for name, stats in ARMOR.items():
        owned = "✅" if name in player.dungeon["inventory"] else ""
        rarity_emoji = {"common": "⚪", "uncommon": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟡", "mythic": "🔴", "divine": "✨"}
        rarity = rarity_emoji.get(stats.get("rarity", "common"), "")
        text += f"{owned} {rarity} 🛡️ {name}: +{stats['defense']} DEF - {stats['cost']:,} coins\n"
    
    text += f"\n**💍 Phụ kiện:**\n"
    for name, stats in ACCESSORIES.items():
        owned = "✅" if name in player.dungeon["inventory"] else ""
        rarity_emoji = {"common": "⚪", "uncommon": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟡", "mythic": "🔴", "divine": "✨"}
        rarity = rarity_emoji.get(stats.get("rarity", "common"), "")
        text += f"{owned} {rarity} 💍 {name}: +{stats['attack']} ATK, +{stats['defense']} DEF - {stats['cost']:,} coins\n"
    
    text += f"\n**🧪 Thuốc:**\n"
    for name, stats in POTIONS.items():
        rarity_emoji = {"common": "⚪", "uncommon": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟡"}
        rarity = rarity_emoji.get(stats.get("rarity", "common"), "")
        text += f"{rarity} 🧪 {name}: Hồi {stats['heal']} HP - {stats['cost']:,} coins\n"
    
    text += f"\n**🪝 Cần câu:** (Xem /rodshop để xem tất cả)\n"
    current_rod = player.fishing.get("rod_name", "Wooden Rod")
    rod_list = list(FISHING_RODS.keys())
    try:
        current_index = rod_list.index(current_rod)
        # Show next 5 rods
        for i in range(current_index + 1, min(current_index + 6, len(rod_list))):
            rod_name = rod_list[i]
            rod_data = FISHING_RODS[rod_name]
            text += f"🪝 {rod_name}: {rod_data['cost']:,} coins\n"
    except ValueError:
        pass
    
    text += f"\n**🐾 Pet:**\n"
    for pet_name, pet_data in PETS.items():
        owned = "✅" if pet_name in player.pets.get("owned", []) else ""
        text += f"{owned} {pet_data['emoji']} {pet_name}: {pet_data['cost']:,} coins\n"
    
    text += "\nSử dụng /buy <tên vật phẩm> để mua"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Menu Chính", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()


@router.message(Command("buy"))
async def cmd_buy(message: Message):
    """Buy item command"""
    try:
        item_name = " ".join(message.text.split()[1:])
    except IndexError:
        await message.answer("❌ Sử dụng: /buy <tên vật phẩm>")
        return
    
    player = await DataManager.get_player(message.from_user.id)
    
    # Check if item exists
    if item_name in WEAPONS:
        item_data = WEAPONS[item_name]
        if item_name in player.dungeon["inventory"]:
            await message.answer(f"✅ Bạn đã có {item_name} rồi!")
            return
    elif item_name in ARMOR:
        item_data = ARMOR[item_name]
        if item_name in player.dungeon["inventory"]:
            await message.answer(f"✅ Bạn đã có {item_name} rồi!")
            return
    elif item_name in ACCESSORIES:
        item_data = ACCESSORIES[item_name]
        if item_name in player.dungeon["inventory"]:
            await message.answer(f"✅ Bạn đã có {item_name} rồi!")
            return
    elif item_name in POTIONS:
        item_data = POTIONS[item_name]
        # Potions can be bought multiple times
    elif item_name in FISHING_RODS:
        item_data = FISHING_RODS[item_name]
        current_rod = player.fishing.get("rod_name", "Wooden Rod")
        if item_name == current_rod:
            await message.answer(f"✅ Bạn đã có {item_name} rồi!")
            return
        # Check if player has previous rod
        rod_list = list(FISHING_RODS.keys())
        try:
            current_index = rod_list.index(current_rod)
            item_index = rod_list.index(item_name)
            if item_index <= current_index:
                await message.answer("❌ Bạn cần mua các cần câu trước đó trước!")
                return
        except ValueError:
            pass
    elif item_name in PETS:
        item_data = PETS[item_name]
        if item_name in player.pets.get("owned", []):
            await message.answer(f"✅ Bạn đã có {item_name} rồi!")
            return
    else:
        await message.answer("❌ Vật phẩm không tồn tại! Xem /shop")
        return
    
    if player.coins < item_data["cost"]:
        await message.answer(f"❌ Bạn không đủ coins! Cần {item_data['cost']:,} coins")
        return
    
    player.coins -= item_data["cost"]
    
    if item_name in FISHING_RODS:
        player.fishing["rod_name"] = item_name
        await message.answer(f"✅ Đã mua {item_name}!")
    elif item_name in PETS:
        if "owned" not in player.pets:
            player.pets["owned"] = []
        player.pets["owned"].append(item_name)
        if "pet_level" not in player.pets:
            player.pets["pet_level"] = {}
        player.pets["pet_level"][item_name] = 1
        await message.answer(f"✅ Đã mua {item_name}! Sử dụng /pet {item_name} để kích hoạt")
    elif item_name in POTIONS:
        # Potions can stack, just add to inventory
        player.dungeon["inventory"].append(item_name)
        await message.answer(f"✅ Đã mua {item_name}!")
    else:
        player.dungeon["inventory"].append(item_name)
        await message.answer(f"✅ Đã mua {item_name}!")
    
    await DataManager.save_player(player)


@router.callback_query(F.data == "stats")
async def callback_stats(callback: CallbackQuery):
    """View stats"""
    player = await DataManager.get_player(callback.from_user.id)
    
    # Calculate stats
    total_fish_value = sum(FISH_TYPES.get(f, {}).get("coins", 0) for f in player.fishing["caught_fish"])
    
    text = (
        f"📊 **THỐNG KÊ**\n\n"
        f"💰 Tổng coins đã kiếm: ~{player.coins + total_fish_value:,}\n"
        f"⭐ Level: {player.level}\n"
        f"📊 EXP: {player.exp}/{player.level * 100}\n\n"
        f"🎣 **Câu Cá:**\n"
        f"  🐟 Tổng cá: {player.fishing['total_caught']}\n"
        f"  🪝 Cần câu: Cấp {player.fishing['rod_level']}\n\n"
        f"⚔️ **Hầm Ngục:**\n"
        f"  🏆 Tầng cao nhất: {player.dungeon['max_floor']}\n"
        f"  🎒 Vật phẩm: {len(player.dungeon['inventory'])}\n\n"
        f"🎰 **RNG:**\n"
        f"  🎴 Thẻ đã mở: {player.rng['cards_opened']}\n"
        f"  📚 Thẻ sở hữu: {len(player.rng['cards'])}/{len(RNG_CARDS)}\n"
        f"  🎰 Slots: {player.rng['slots_played']} lần\n"
        f"  🎲 Dice thắng: {player.rng['dice_wins']}\n"
        f"  ✨ Jackpot: {player.rng['jackpot_won']}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Menu Chính", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()


# ==================== MAIN ====================

async def main():
    """Main function"""
    logger.info("Loading player data...")
    await DataManager.load_players()
    
    logger.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
        asyncio.run(DataManager.save_players())
