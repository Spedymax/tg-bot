import random
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional
from models.player import Player
from config.game_config import GameConfig

class GameService:
    def __init__(self, player_service):
        self.player_service = player_service
        
    def calculate_pisunchik_cooldown(self, player: Player) -> int:
        """Calculate cooldown based on Titan characteristic"""
        cooldown_hours = GameConfig.PISUNCHIK_COOLDOWN_HOURS
        
        if player.has_characteristic('Titan'):
            titan_level = player.get_characteristic_level('Titan')
            reduction = GameConfig.CHARACTERISTIC_EFFECTS['Titan']['base_reduction'] * titan_level
            cooldown_hours = int((24 * (100 - reduction)) / 100)
            
        return cooldown_hours
    
    def can_use_pisunchik(self, player: Player) -> Tuple[bool, Optional[timedelta]]:
        """Check if player can use pisunchik command"""
        cooldown_hours = self.calculate_pisunchik_cooldown(player)
        time_since_last = datetime.now(timezone.utc) - player.last_used
        
        if time_since_last < timedelta(hours=cooldown_hours):
            time_left = timedelta(hours=cooldown_hours) - time_since_last
            return False, time_left
        
        return True, None
    
    def apply_item_effects(self, player: Player, size_change: int, coins_change: int) -> Tuple[int, int, List[str]]:
        """Apply item effects and return modified values with effect messages"""
        effects_applied = []
        
        # Crystal balls effect
        if player.has_item('krystalnie_ballzzz') and player.ballzzz_number is not None:
            size_change = player.ballzzz_number
            player.ballzzz_number = None
            player.remove_item('krystalnie_ballzzz')
        
        # Ring effect (double coins)
        if player.has_item('kolczo_na_chlen') and random.random() <= GameConfig.ITEM_EFFECTS['kolczo_na_chlen']['probability']:
            coins_change *= GameConfig.ITEM_EFFECTS['kolczo_na_chlen']['multiplier']
            effects_applied.append("Эффект от 'kolczo_na_chlen': количество полученного BTC УДВОЕНО!")
        
        # Condom protection
        if player.has_item('prezervativ') and size_change < 0:
            current_time = datetime.now(timezone.utc)
            cooldown_days = GameConfig.ITEM_EFFECTS['prezervativ']['cooldown_days']
            
            if current_time - player.last_prezervativ >= timedelta(days=cooldown_days):
                size_change = 0
                player.last_prezervativ = current_time
                effects_applied.append("Эффект от 'prezervativ': писюнчик не уменьшился.")
            else:
                effects_applied.append("'prezervativ' еще на кулдауне.")
        
        # BDSM costume effect
        if player.has_item('bdsm_kostumchik') and random.random() <= GameConfig.ITEM_EFFECTS['bdsm_kostumchik']['probability']:
            size_change += GameConfig.ITEM_EFFECTS['bdsm_kostumchik']['bonus']
            effects_applied.append("Эффект от 'bdsm_kostumchik': +5 см к писюнчику получено.")
        
        return size_change, coins_change, effects_applied
    
    def execute_pisunchik_command(self, player: Player) -> Dict:
        """Execute the pisunchik command and return results"""
        # Check cooldown
        can_use, time_left = self.can_use_pisunchik(player)
        if not can_use:
            return {
                'success': False,
                'message': f"Вы можете использовать эту команду только раз в день\nОсталось времени: {time_left}",
                'on_cooldown': True
            }
        
        # Update last used time
        player.last_used = datetime.now(timezone.utc)
        
        # Calculate base changes
        size_change = random.randint(GameConfig.PISUNCHIK_MIN_CHANGE, GameConfig.PISUNCHIK_MAX_CHANGE)
        coins_change = random.randint(GameConfig.PISUNCHIK_MIN_COINS, GameConfig.PISUNCHIK_MAX_COINS)
        
        # Apply item effects
        size_change, coins_change, effects = self.apply_item_effects(player, size_change, coins_change)
        
        # Update player stats
        player.pisunchik_size += size_change
        player.add_coins(coins_change)
        player.notified = False
        
        # Set next ballzzz effect
        player.ballzzz_number = random.randint(GameConfig.PISUNCHIK_MIN_CHANGE, GameConfig.PISUNCHIK_MAX_CHANGE)
        
        # Save player
        self.player_service.save_player(player)
        
        return {
            'success': True,
            'size_change': size_change,
            'coins_change': coins_change,
            'new_size': player.pisunchik_size,
            'new_coins': player.coins,
            'effects': effects,
            'on_cooldown': False
        }
    
    def can_use_casino(self, player: Player) -> Tuple[bool, Optional[str]]:
        """Check if player can use casino"""
        current_time = datetime.now(timezone.utc)
        
        if player.casino_last_used:
            time_elapsed = current_time - player.casino_last_used
            
            if time_elapsed < timedelta(hours=24) and player.casino_usage_count >= GameConfig.CASINO_DAILY_LIMIT:
                time_left = timedelta(days=1) - time_elapsed
                return False, f"Вы достигли лимита использования команды на сегодня.\nВремени осталось: {time_left}"
            elif time_elapsed >= timedelta(hours=24):
                player.casino_usage_count = 0
        
        return True, None
    
    def execute_casino_command(self, player: Player) -> Dict:
        """Execute casino command with 6 casino dice throws"""
        can_use, error_message = self.can_use_casino(player)
        if not can_use:
            return {'success': False, 'message': error_message}
        
        player.casino_last_used = datetime.now(timezone.utc)
        player.casino_usage_count += 1
        
        # Mark that we need to send 6 casino dice
        # The actual dice sending will be handled in the handler
        self.player_service.save_player(player)
        
        return {
            'success': True,
            'send_dice': True,  # Signal to handler to send 6 dice
            'dice_count': 6
        }
    
    
    def calculate_roll_cost(self, rolls: int, player: Player) -> int:
        """Calculate cost for roll command with discounts"""
        base_cost = GameConfig.ROLL_COSTS.get(rolls, rolls * 6)
        
        # Apply sex dice discount
        if player.has_item('kubik_seksa'):
            base_cost = int(base_cost * GameConfig.ITEM_EFFECTS['kubik_seksa']['reduction_factor'])
        
        # Apply invisible characteristic free rolls
        if player.has_characteristic('Invisible'):
            invisible_level = player.get_characteristic_level('Invisible')
            probability = (GameConfig.CHARACTERISTIC_EFFECTS['Invisible']['base_probability'] + 
                         (invisible_level - 1) * GameConfig.CHARACTERISTIC_EFFECTS['Invisible']['probability_per_level'])
            
            free_rolls = 0
            for _ in range(rolls):
                if random.random() <= probability:
                    free_rolls += 1
            
            # Reduce cost based on free rolls
            cost_per_roll = base_cost // rolls if rolls > 0 else 6
            base_cost -= free_rolls * cost_per_roll
        
        return max(0, base_cost)
    
    def execute_roll_command(self, player: Player, rolls: int) -> Dict:
        """Execute roll command"""
        cost = self.calculate_roll_cost(rolls, player)
        
        if not player.spend_coins(cost):
            return {
                'success': False,
                'message': f"Недостаточно BTC. Нужно {cost} BTC"
            }
        
        results = []
        jackpots = 0
        
        for _ in range(rolls):
            roll = random.randint(1, 6)
            results.append(roll)
            
            # Apply size changes
            if roll <= GameConfig.DICE_LOSS_THRESHOLD:
                player.pisunchik_size -= GameConfig.DICE_SIZE_CHANGE
            else:
                player.pisunchik_size += GameConfig.DICE_SIZE_CHANGE
            
            # Check for jackpot (1% chance)
            if random.randint(1, 101) == 14:
                jackpots += 1
                player.add_coins(400)
        
        self.player_service.save_player(player)
        
        return {
            'success': True,
            'cost': cost,
            'results': results,
            'jackpots': jackpots,
            'new_size': player.pisunchik_size,
            'jackpot_coins': jackpots * 400
        }
    
    def can_steal(self, player: Player) -> Tuple[bool, Optional[str]]:
        """Check if player can use theft command"""
        if not player.has_characteristic('Glowing'):
            return False, "У вас нету нужной характеристики для писюничка :("
        
        current_time = datetime.now(timezone.utc)
        time_elapsed = current_time - player.last_vor
        
        if time_elapsed < timedelta(days=GameConfig.VOR_COOLDOWN_DAYS):
            time_left = timedelta(days=GameConfig.VOR_COOLDOWN_DAYS) - time_elapsed
            return False, f"Вы достигли лимита использования команды на эту неделю.\nВремени осталось: {time_left}"
        
        return True, None
    
    def execute_theft(self, thief: Player, victim: Player) -> Dict:
        """Execute theft between players"""
        can_steal, error_message = self.can_steal(thief)
        if not can_steal:
            return {'success': False, 'message': error_message}
        
        # Calculate theft amount based on Glowing level
        glowing_level = thief.get_characteristic_level('Glowing')
        theft_amount = (GameConfig.CHARACTERISTIC_EFFECTS['Glowing']['base_amount'] + 
                       (glowing_level - 1) * GameConfig.CHARACTERISTIC_EFFECTS['Glowing']['amount_per_level'])
        
        # Update last theft time
        thief.last_vor = datetime.now(timezone.utc)
        
        # Transfer size
        victim.pisunchik_size -= theft_amount
        thief.pisunchik_size += theft_amount
        
        # Save both players
        self.player_service.save_player(thief)
        self.player_service.save_player(victim)
        
        return {
            'success': True,
            'amount': theft_amount,
            'thief_name': thief.player_name,
            'victim_name': victim.player_name
        }
    
    def calculate_shop_discount(self, player: Player, base_price: int) -> int:
        """Calculate shop discount based on Hot characteristic"""
        if not player.has_characteristic('Hot'):
            return base_price
        
        hot_level = player.get_characteristic_level('Hot')
        discount_percent = (GameConfig.CHARACTERISTIC_EFFECTS['Hot']['base_discount'] + 
                          (hot_level - 1) * GameConfig.CHARACTERISTIC_EFFECTS['Hot']['discount_per_level'])
        
        discounted_price = int(base_price * (100 - discount_percent) / 100)
        return discounted_price
    
    def upgrade_characteristic(self, player: Player, characteristic_name: str, levels: int) -> Dict:
        """Upgrade a player's characteristic"""
        current_level = player.get_characteristic_level(characteristic_name)
        new_level = current_level + levels
        
        if new_level > GameConfig.MAX_CHARACTERISTIC_LEVEL:
            return {'success': False, 'message': 'Превышен максимальный уровень.'}
        
        cost = GameConfig.UPGRADE_COST_PER_LEVEL * levels
        
        if not player.spend_coins(cost):
            return {'success': False, 'message': 'Недостаточно денег для улучшения.'}
        
        player.update_characteristic_level(characteristic_name, new_level)
        self.player_service.save_player(player)
        
        return {
            'success': True,
            'characteristic': characteristic_name,
            'new_level': new_level,
            'cost': cost
        }
    
    def use_masturbator(self, player: Player, donation_amount: int) -> Dict:
        """Use masturbator item"""
        if not player.has_item('masturbator'):
            return {'success': False, 'message': "У вас нету предмета 'masturbator'"}
        
        if donation_amount <= 0:
            return {'success': False, 'message': 'Пожалуйста, введите позитивное число. (Не балуйся)'}
        
        if donation_amount > player.pisunchik_size:
            return {'success': False, 'message': 'Вы не можете пожертвовать больше, чем у вас есть. Дурак совсем?'}
        
        # Calculate coins awarded
        coins_awarded = donation_amount * 4 + (donation_amount // 5) * 5
        
        # Update player
        player.pisunchik_size -= donation_amount
        player.add_coins(coins_awarded)
        player.remove_item('masturbator')
        
        self.player_service.save_player(player)
        
        return {
            'success': True,
            'donated': donation_amount,
            'coins_received': coins_awarded,
            'new_size': player.pisunchik_size
        }
    
    def apply_daily_effects(self, player: Player) -> List[str]:
        """Apply daily effects like Gold characteristic income"""
        effects = []
        
        if player.has_characteristic('Gold'):
            gold_level = player.get_characteristic_level('Gold')
            income = (GameConfig.CHARACTERISTIC_EFFECTS['Gold']['base_income'] + 
                     (gold_level - 1) * GameConfig.CHARACTERISTIC_EFFECTS['Gold']['income_per_level'])
            player.add_coins(int(income))
            effects.append(f"Ваш золотой член принёс сегодня прибыль в размере {int(income)} BTC")
        
        if player.has_characteristic('Big Black'):
            big_black_level = player.get_characteristic_level('Big Black')
            min_size = (GameConfig.CHARACTERISTIC_EFFECTS['Big Black']['base_minimum'] + 
                       (big_black_level - 1) * GameConfig.CHARACTERISTIC_EFFECTS['Big Black']['minimum_per_level'])
            
            if player.pisunchik_size < min_size:
                player.pisunchik_size = min_size
                effects.append(f"Ваш член менее {min_size} сантиметров :( Но благодаря Big Black характеристике ваш член снова стал {min_size} см")
        
        if effects:
            self.player_service.save_player(player)
        
        return effects
