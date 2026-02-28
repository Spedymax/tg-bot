"""
Game configuration constants for the Telegram bot
"""

class GameConfig:
    # Pisunchik game settings
    PISUNCHIK_COOLDOWN_HOURS = 24
    PISUNCHIK_MIN_CHANGE = -10
    PISUNCHIK_MAX_CHANGE = 17
    PISUNCHIK_MIN_COINS = 5
    PISUNCHIK_MAX_COINS = 15
    
    # Casino settings
    CASINO_DAILY_LIMIT = 5
    CASINO_JACKPOT_VALUES = {1, 22, 43, 64}
    CASINO_JACKPOT_REWARD = 300
    CASINO_DICE_DELAY = 1  # Delay between dice rolls (seconds)
    CASINO_ANIMATION_WAIT = 3  # Wait after last die for animations to finish

    # Roll game animation delays
    ROLL_JACKPOT_DELAY = 2  # Delay before jackpot announcement (seconds)
    
    # Roll game settings
    ROLL_COSTS = {
        1: 6,
        3: 18,
        5: 30,
        10: 60,
        20: 120,
        50: 300,
        100: 600
    }
    
    # Dice game settings
    DICE_LOSS_THRESHOLD = 3  # Values <= 3 are losses
    DICE_SIZE_CHANGE = 5     # Size change per dice roll
    
    # Theft settings (vor command)
    VOR_COOLDOWN_DAYS = 7
    VOR_BASE_AMOUNT = 2  # Base amount stolen
    
    # Item effects
    ITEM_EFFECTS = {
        'kolczo_na_chlen': {
            'type': 'coins_multiplier',
            'probability': 0.2,
            'multiplier': 2
        },
        'bdsm_kostumchik': {
            'type': 'size_bonus',
            'probability': 0.1,
            'bonus': 5
        },
        'prezervativ': {
            'type': 'protection',
            'cooldown_days': 4
        },
        'kubik_seksa': {
            'type': 'cost_reduction',
            'reduction_factor': 0.5
        }
    }
    
    # Characteristic effects
    CHARACTERISTIC_EFFECTS = {
        'Titan': {
            'type': 'cooldown_reduction',
            'base_reduction': 3,  # Percentage per level
            'max_level': 15
        },
        'Hot': {
            'type': 'shop_discount',
            'base_discount': 5,  # Percentage per level
            'discount_per_level': 3
        },
        'Invisible': {
            'type': 'free_rolls',
            'base_probability': 0.03,
            'probability_per_level': 0.03
        },
        'Glowing': {
            'type': 'theft_amount',
            'base_amount': 2,
            'amount_per_level': 2
        },
        'Gold': {
            'type': 'passive_income',
            'base_income': 2,
            'income_per_level': 1.5
        },
        'Big Black': {
            'type': 'minimum_size',
            'base_minimum': 0,
            'minimum_per_level': 3
        }
    }
    
    # Shop settings
    UPGRADE_COST_PER_LEVEL = 100
    MAX_CHARACTERISTIC_LEVEL = 15
    
    # Notification settings
    NOTIFICATION_HOUR = 12  # Hour for daily notifications
    TRIVIA_HOURS = [10, 15, 18]  # Hours when trivia is sent
    TRIVIA_RESULTS_HOUR = 21
    TRIVIA_RESULTS_MINUTE = 50
    
    # Stock market settings
    STOCK_CHANGE_RANGE = (-0.1, 0.4)  # Min and max percentage change
    STOCK_UPDATE_HOURS = [8, 13, 17]
    
    # Message cleanup settings
    MESSAGE_RETENTION_HOURS = 12
    MAX_MESSAGES_COUNT = 300
