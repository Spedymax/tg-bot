import random
from typing import Dict, Set, Tuple, Any


class StockService:
    """Service to manage stock price updates and transactions."""

    def update_stock_prices(self, cursor: Any):
        """Fetch and update stock prices randomly."""
        query = "SELECT company_name, price FROM stocks"
        cursor.execute(query)
        stock_data = cursor.fetchall()
        
        # Store old prices in a dictionary for comparison
        old_prices = {company: price for company, price in stock_data}
        
        for company, old_price in old_prices.items():
            # Randomly increase or decrease price
            change_percent = random.uniform(-0.1, 0.4)
            new_price = round(old_price * (1 + change_percent), 2)
            if new_price == 0.0:
                new_price = 1
            
            update_query = "UPDATE stocks SET price = %s WHERE company_name = %s"
            cursor.execute(update_query, (new_price, company))


    def get_stock_data(self, cursor: Any) -> Dict[str, float]:
        """Retrieve all stock data from the database."""
        query = "SELECT company_name, price FROM stocks"
        cursor.execute(query)
        return dict(cursor.fetchall())

    def process_stock_transaction(self, participant_stocks: Set[str], company: str, quantity: int,
                                  stock_price: float, increase: bool) -> Tuple[Set[str], float]:
        """Process buying or selling of stocks for a participant."""

        participant_stocks = set(participant_stocks)
        
        # Increase or decrease stock quantity
        operation, factor = ('+', 1) if increase else ('-', -1)

        stock_record = next((stock for stock in participant_stocks if stock.startswith(company)), None)
        original_quantity, updated_stocks = (0, participant_stocks)

        if stock_record:
            parts = stock_record.split(':')
            if len(parts) >= 2:
                try:
                    original_quantity = int(parts[1])
                except ValueError:
                    original_quantity = 0
            participant_stocks.remove(stock_record)

        new_quantity = max(0, original_quantity + (quantity * factor))

        if new_quantity > 0:
            participant_stocks.add(f"{company}:{new_quantity}")

        total_cost = stock_price * quantity * factor
        return participant_stocks, total_cost
    
    def calculate_price_change(self, old_price: float, new_price: float) -> Tuple[float, str]:
        """Calculate price change and determine arrow direction."""
        if old_price == 0:
            # Avoid division by zero
            change = 100.0 if new_price > 0 else 0.0
        else:
            change = ((new_price - old_price) / old_price) * 100
        arrow = '⬆️' if change > 0 else '⬇️'
        return change, arrow

