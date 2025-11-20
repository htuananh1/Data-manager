"""
Fishing Game Data - 200 Fish Types, 50 Rods, Pet System
"""
import random

# Generate 200 fish types
def generate_fish_types():
    """Generate 200 fish types with different rarities"""
    fish_emojis = ['🐟', '🐠', '🐡', '🦈', '🐋', '🐬', '🦑', '🐙', '🦀', '🦞', '🦐', '🦭']
    fish_names_base = [
        "Cá rô", "Cá chép", "Cá trắm", "Cá mè", "Cá diếc", "Cá trôi", "Cá chạch", "Cá rô phi",
        "Cá trắng", "Cá mương", "Cá bống", "Cá kèo", "Cá lòng tong", "Cá sặc", "Cá thát lát",
        "Cá linh", "Cá bạc má", "Cá cơm", "Cá nục", "Cá trích", "Cá mòi", "Cá hố", "Cá thu",
        "Cá ngừ", "Cá nục gai", "Cá đuối", "Cá nhám", "Cá bơn", "Cá bẹ", "Cá chim", "Cá mú",
        "Cá hồng", "Cá cam", "Cá chẽm", "Cá vược", "Cá đối", "Cá dìa", "Cá trê", "Cá lóc",
        "Cá quả", "Cá chuối", "Cá sộp", "Cá tầm", "Cá hồi", "Cá chình", "Cá lươn", "Cá trạch",
        "Cá mập", "Cá voi", "Cá heo", "Cá nhám voi", "Cá đuối khổng lồ", "Cá mặt trăng",
        "Cá nạng hải", "Cá cờ", "Cá kiếm", "Cá vàng thần", "Cá rồng", "Cá phượng", "Cá kỳ lân",
    ]
    
    fish_types = {}
    fish_id = 0
    
    # Common fish (80)
    for i in range(80):
        if i < len(fish_names_base):
            name = fish_names_base[i]
        else:
            name = f"Cá thường {i+1}"
        emoji = fish_emojis[i % len(fish_emojis)]
        coins = random.randint(5, 20)
        exp = random.randint(3, 10)
        fish_types[name] = {"rarity": "common", "coins": coins, "exp": exp, "emoji": emoji}
        fish_id += 1
    
    # Uncommon fish (60)
    for i in range(60):
        if i + 80 < len(fish_names_base):
            name = f"{fish_names_base[i + 80]} hiếm"
        else:
            name = f"Cá hiếm {i+1}"
        emoji = fish_emojis[i % len(fish_emojis)]
        coins = random.randint(25, 60)
        exp = random.randint(10, 20)
        fish_types[name] = {"rarity": "uncommon", "coins": coins, "exp": exp, "emoji": emoji}
        fish_id += 1
    
    # Rare fish (40)
    for i in range(40):
        if i + 140 < len(fish_names_base):
            name = f"{fish_names_base[i + 140]} quý"
        else:
            name = f"Cá quý {i+1}"
        emoji = fish_emojis[i % len(fish_emojis)]
        coins = random.randint(80, 200)
        exp = random.randint(20, 40)
        fish_types[name] = {"rarity": "rare", "coins": coins, "exp": exp, "emoji": emoji}
        fish_id += 1
    
    # Epic fish (15)
    for i in range(15):
        if i + 180 < len(fish_names_base):
            name = f"{fish_names_base[i + 180]} huyền thoại"
        else:
            name = f"Cá huyền thoại {i+1}"
        emoji = fish_emojis[i % len(fish_emojis)]
        coins = random.randint(250, 800)
        exp = random.randint(50, 150)
        fish_types[name] = {"rarity": "epic", "coins": coins, "exp": exp, "emoji": emoji}
        fish_id += 1
    
    # Legendary fish (5)
    legendary_names = ["Cá vàng thần", "Cá rồng vàng", "Cá phượng hoàng", "Cá kỳ lân", "Cá thần long"]
    for i, name in enumerate(legendary_names):
        emoji = "✨" if i == 0 else "👑"
        coins = random.randint(1000, 5000)
        exp = random.randint(200, 500)
        fish_types[name] = {"rarity": "legendary", "coins": coins, "exp": exp, "emoji": emoji}
    
    return fish_types


# Generate 50 fishing rods with effects
def generate_rods():
    """Generate 50 fishing rods with different effects and auto-adjusted prices"""
    rod_effects = [
        {"name": "increase_rare_rate", "value": 0.1, "description": "Tăng tỷ lệ cá hiếm"},
        {"name": "increase_coins", "value": 0.2, "description": "Tăng coins nhận được"},
        {"name": "increase_exp", "value": 0.3, "description": "Tăng EXP nhận được"},
        {"name": "double_catch", "value": 0.05, "description": "Có thể câu 2 cá cùng lúc"},
        {"name": "reduce_bait", "value": 0.1, "description": "Giảm tiêu hao mồi"},
    ]
    
    rod_names = [
        "Wooden Rod", "Bamboo Rod", "Iron Rod", "Steel Rod", "Titanium Rod",
        "Carbon Rod", "Diamond Rod", "Platinum Rod", "Mithril Rod", "Adamantite Rod",
        "Crystal Rod", "Emerald Rod", "Sapphire Rod", "Ruby Rod", "Topaz Rod",
        "Amethyst Rod", "Pearl Rod", "Coral Rod", "Seashell Rod", "Kraken Rod",
        "Poseidon Rod", "Neptune Rod", "Triton Rod", "Siren Rod", "Mermaid Rod",
        "Dragon Rod", "Phoenix Rod", "Unicorn Rod", "Griffin Rod", "Pegasus Rod",
        "Celestial Rod", "Divine Rod", "God Rod", "Titan Rod", "Olympus Rod",
        "Cosmic Rod", "Stellar Rod", "Nebula Rod", "Galaxy Rod", "Universe Rod",
        "Infinity Rod", "Eternal Rod", "Immortal Rod", "Transcendent Rod", "Ascended Rod",
        "Primordial Rod", "Ancient Rod", "Mythic Rod", "Legendary Rod", "Ultimate Rod",
    ]
    
    rods = {}
    base_cost = 0
    
    for i, rod_name in enumerate(rod_names):
        # Auto-adjust price based on rod index and effects
        tier = (i // 10) + 1
        base_cost = int(100 * (1.5 ** i))  # Exponential growth
        
        # Select random effects (1-3 effects per rod)
        num_effects = min(3, max(1, (i // 15) + 1))
        effects = random.sample(rod_effects, num_effects)
        
        rod_effects_dict = {}
        for effect in effects:
            rod_effects_dict[effect["name"]] = effect["value"] * (1 + tier * 0.1)
        
        # Calculate catch rates based on tier
        common_rate = max(20, 80 - tier * 5)
        uncommon_rate = min(40, 15 + tier * 2)
        rare_rate = min(25, 3 + tier * 1.5)
        epic_rate = min(10, 1 + tier * 0.5)
        legendary_rate = min(5, 0.1 + tier * 0.1)
        
        rods[rod_name] = {
            "cost": base_cost,
            "tier": tier,
            "effects": rod_effects_dict,
            "catch_rates": {
                "common": common_rate,
                "uncommon": uncommon_rate,
                "rare": rare_rate,
                "epic": epic_rate,
                "legendary": legendary_rate,
            },
            "description": ", ".join([e["description"] for e in effects]),
        }
    
    return rods


# Pet system
PETS = {
    "Cá vàng": {
        "emoji": "🐠",
        "rarity": "common",
        "cost": 500,
        "effects": {"increase_coins": 0.1},
        "description": "Tăng 10% coins khi câu cá",
    },
    "Cá heo": {
        "emoji": "🐬",
        "rarity": "uncommon",
        "cost": 2000,
        "effects": {"increase_exp": 0.15},
        "description": "Tăng 15% EXP khi câu cá",
    },
    "Cá mập": {
        "emoji": "🦈",
        "rarity": "rare",
        "cost": 10000,
        "effects": {"increase_rare_rate": 0.2},
        "description": "Tăng 20% tỷ lệ cá hiếm",
    },
    "Cá voi": {
        "emoji": "🐋",
        "rarity": "epic",
        "cost": 50000,
        "effects": {"increase_coins": 0.25, "increase_exp": 0.25},
        "description": "Tăng 25% coins và EXP",
    },
    "Rồng biển": {
        "emoji": "🐉",
        "rarity": "legendary",
        "cost": 200000,
        "effects": {"increase_rare_rate": 0.3, "increase_coins": 0.3, "increase_exp": 0.3},
        "description": "Tăng 30% tất cả hiệu ứng",
    },
    "Thần biển": {
        "emoji": "🧜",
        "rarity": "mythic",
        "cost": 1000000,
        "effects": {"increase_rare_rate": 0.5, "increase_coins": 0.5, "double_catch": 0.1},
        "description": "Tăng 50% hiếm/coins, 10% câu đôi",
    },
}

# Initialize data
FISH_TYPES = generate_fish_types()
FISHING_RODS = generate_rods()
