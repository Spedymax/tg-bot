import random

class CasinoMiniApp:
    def __init__(self, player_service):
        self.player_service = player_service
        self.daily_spin_limit = 6

    def spin_wheel(self, player_id):
        player = self.player_service.get_player(player_id)
        if not player:
            return "Игрок не найден."

        spins_left = self.get_daily_spins_left(player)
        if spins_left <= 0:
            return "Вы уже использовали все свои спины на сегодня."

        result = self.generate_spin_result()
        self.apply_spin_result(player, result)
        self.save_spin_data(player)

        return f"Вы выиграли: {result}!\nУ вас осталось спинов: {spins_left - 1}"

    def get_daily_spins_left(self, player):
        # Here you would access player's daily spin count from persistent storage
        # For example purposes, we'll create a dummy attribute
        
        if not hasattr(player, 'daily_spins'): 
            player.daily_spins = 0

        spins_left = self.daily_spin_limit - player.daily_spins
        return max(0, spins_left)

    def generate_spin_result(self):
        possible_results = ['10 BTC', 'Спасибо за игру!', '2x выигрыш!', 'Попробуй еще раз!', 'Лучшее время впереди!', '50 BTC']
        return random.choice(possible_results)

    def apply_spin_result(self, player, result):
        # Logic to apply the spin result
        if result.endswith('BTC'):
            btc_amount = int(result.split()[0])
            player.coins += btc_amount
        elif result == '2x выигрыш!':
            player.coins *= 2
        # Add more logic for different results if needed

    def save_spin_data(self, player):
        # Save player's spin data
        player.daily_spins += 1
        self.player_service.save_player(player)
