from telebot import types
import random

def update_stock_prices(cursor, bot, helper):
    # Fetch the stock data
    query = "SELECT company_name, price FROM stocks"
    cursor.execute(query)
    stock_data = cursor.fetchall()

    # Store old prices in a dictionary for comparison
    old_prices = {company: price for company, price in stock_data}

    for company, old_price in old_prices.items():
        # Randomly increase or decrease price by up to 10%
        change_percent = random.uniform(-0.2, 0.2)
        new_price = round(old_price * (1 + change_percent), 2)

        # Update the new price in the database
        update_query = "UPDATE stocks SET price = %s WHERE company_name = %s"
        cursor.execute(update_query, (new_price, company))

    # Fetch updated stock data
    cursor.execute(query)
    updated_stock_data = cursor.fetchall()

    # Format the message
    stock_message = "Акции компаний на данный момент:\n\n"
    for company, new_price in updated_stock_data:
        old_price = old_prices[company]
        change = ((new_price - old_price) / old_price) * 100
        arrow = '⬆️' if change > 0 else '⬇️'
        stock_message += f"{company}: {new_price} BTC ({abs(change):.2f}% {arrow})\n"

    # Send the message
    helper.send_message_to_group(bot, stock_message)
    helper.send_message_to_group(bot,
                     "Чтобы купить акции используйте /buy_stocks \nЧтобы посмотреть свои акции используйте /my_stocks. \nЧтобы посмотреть стоимость акций на данный момент используйте /current_stocks")


def stocks_update(message, bot, admin_ids, cursor, helper):
    if message.from_user.id in admin_ids:
        update_stock_prices(cursor, bot, helper)
    else:
        bot.send_message(message.chat.id, "Вы не админ((((((((((((")


def current_stocks(message, cursor, bot):
    query = "SELECT * FROM stocks"
    cursor.execute(query)
    stock_data = cursor.fetchall()
    stock_message = "Акции компаний на данный момент:\n\n"
    for company, price in stock_data:
        stock_message += f"{company}: {price} BTC\n"

    # Send the message
    bot.reply_to(message, stock_message)


def my_stocks(message, pisunchik, cursor, bot):
    player_id = str(message.from_user.id)
    if player_id in pisunchik:
        stocks_text = "Ваши акции:\n"
        existing_stoks = pisunchik[player_id]['player_stocks']
        for player_stocks in existing_stoks:
            company_name, quantity = player_stocks.split(":")
            cursor.execute("SELECT price FROM stocks WHERE company_name = %s", (company_name,))
            result = cursor.fetchone()
            if not result:
                bot.reply_to(message, f"Company {company_name} not found.")
                return
            quantity = int(quantity)
            stock_price = result[0]
            total_cost = stock_price * quantity
            stocks_text += f"Компания {company_name}, кол-во акций: {quantity}  \n Цена ваших активов компании {company_name}: {total_cost}\n"
        bot.reply_to(message, stocks_text)
    else:
        bot.reply_to(message, "Вы не зарегистрированы как игрок, используйте /start")




def buy_stocks(message, bot):
    markup = types.InlineKeyboardMarkup()
    # Assuming you have a list of companies
    companies = ['ATB', 'Rockstar', 'Google', 'Apple', 'Valve', 'Obuhov toilet paper']
    for company in companies:
        markup.add(types.InlineKeyboardButton(company, callback_data=f"buy_stocks_{company}"))
    bot.send_message(message.chat.id, "Выберите компанию акции которой хотите купить:", reply_markup=markup)


def handle_company_selection(call, bot, temp_user_data):
    company = call.data.split('_')[2]
    temp_user_data[call.from_user.id] = {'company': company}
    msg = f"Сколько акций компании {company} вы хотите купить?"
    bot.send_message(call.message.chat.id, msg)


def handle_quantity_selection(message, bot, cursor, temp_user_data, pisunchik, conn, save_data):
    global user_id
    try:
        quantity = message.text
        if not quantity.isdigit():
            bot.reply_to(message, "Введи норм число, клоун).")
            return

        quantity = int(quantity)
        user_id = message.from_user.id
        company = temp_user_data[user_id]['company']

        # Fetch stock price from the database
        cursor.execute("SELECT price FROM stocks WHERE company_name = %s", (company,))
        result = cursor.fetchone()
        if not result:
            bot.reply_to(message, f"Company {company} not found.")
            return

        stock_price = result[0]
        total_cost = stock_price * quantity
        player_id = str(user_id)
        # Check if the user has enough coins
        if pisunchik[player_id]['coins'] < total_cost:
            bot.reply_to(message, f"Недостаточно BTC для покупки. Надо {total_cost} BTC")
            return

        # Deduct the total cost from the user's coins
        pisunchik[player_id]['coins'] -= total_cost

        # Check if user already owns stocks of this company
        stock_found = False
        for i, stock in enumerate(pisunchik[player_id]['player_stocks']):
            if stock.startswith(company):
                current_quantity = int(stock.split(':')[1])
                new_quantity = current_quantity + quantity
                pisunchik[player_id]['player_stocks'][i] = f"{company}:{new_quantity}"
                stock_found = True
                break

        if not stock_found:
            # Add the new stocks to the player's holdings
            new_stock = f"{company}:{quantity}"
            pisunchik[player_id]['player_stocks'].append(new_stock)

        # Update the player's data in the database
        # Example: UPDATE players SET coins = coins - total_cost, player_stocks = new_stock WHERE player_id = user_id
        cursor.execute("UPDATE pisunchik_data SET coins = %s, player_stocks = %s WHERE player_id = %s",
                       (pisunchik[player_id]['coins'], pisunchik[player_id]['player_stocks'], user_id))
        conn.commit()

        # Inform the user
        bot.reply_to(message, f"Мои поздравления! Вы купили вот столько акций: {quantity}, компании {company}.")
        save_data()
    except Exception as e:
        bot.reply_to(message, f"An error occurred: {str(e)}")
    finally:
        # Clear the temporary data
        if user_id in temp_user_data:
            del temp_user_data[user_id]


def sell_stocks(message, bot, pisunchik):
    markup = types.InlineKeyboardMarkup()
    player_id = str(message.from_user.id)

    if player_id not in pisunchik or not pisunchik[player_id]['player_stocks']:
        bot.send_message(message.chat.id, "Ты бомж, у тебя вообще нету акций.")
        return

    # List the companies the user has stocks in
    owned_stocks = set(stock.split(':')[0] for stock in pisunchik[player_id]['player_stocks'])
    for company in owned_stocks:
        markup.add(types.InlineKeyboardButton(company, callback_data=f"sell_stocks_{company}"))
    bot.send_message(message.chat.id, "Выберите свою компанию:", reply_markup=markup)


def handle_sell_company_selection(call, bot, temp_user_sell_data):
    company = call.data.split('_')[2]
    # Store the selected company in a temporary structure (or user session)
    temp_user_sell_data[call.from_user.id] = {'company_to_sell': company}
    msg = f"Сколько акций компании {company} вы хотите продать?"
    bot.send_message(call.message.chat.id, msg)
    # Next, the user will send a message with the quantity, which you'll handle in a different function


def handle_sell_quantity_selection(message, bot, cursor, temp_user_sell_data, pisunchik, conn, save_data):
    global user_id
    try:
        quantity = message.text
        if not quantity.isdigit():
            bot.reply_to(message, "Введи просто число, клоун)")
            return

        quantity = int(quantity)
        user_id = message.from_user.id
        company = temp_user_sell_data[user_id]['company_to_sell']
        player_id = str(user_id)

        # Check if the user owns enough stocks of the company
        for i, stock in enumerate(pisunchik[player_id]['player_stocks']):
            if stock.startswith(company):
                current_quantity = int(stock.split(':')[1])
                if quantity > current_quantity:
                    bot.reply_to(message, f"У вас нет столько акций. У вас {current_quantity} акций.")
                    return

                # Update the quantity or remove the stock entry if quantity becomes zero
                if quantity < current_quantity:
                    new_quantity = current_quantity - quantity
                    pisunchik[player_id]['player_stocks'][i] = f"{company}:{new_quantity}"
                else:
                    pisunchik[player_id]['player_stocks'].pop(i)
                # Calculate the amount earned from selling the stocks
                # Fetch current stock price from the database
                cursor.execute("SELECT price FROM stocks WHERE company_name = %s", (company,))
                result = cursor.fetchone()
                if not result:
                    bot.reply_to(message, f"Company {company} not found.")
                    return
                current_price = result[0]
                total_earned = current_price * quantity

                # Update player's coins
                pisunchik[player_id]['coins'] += total_earned

                # Update the player's data in the database
                cursor.execute("UPDATE pisunchik_data SET coins = %s, player_stocks = %s WHERE player_id = %s",
                               (pisunchik[player_id]['coins'], pisunchik[player_id]['player_stocks'], user_id))
                conn.commit()

                bot.reply_to(message,
                             f"Вы успешно продали {quantity} акций компании {company}.\n И вы заработали: {total_earned}")
                save_data()


                break
        # Clear the temporary data
        if user_id in temp_user_sell_data:
            del temp_user_sell_data[user_id]
        else:
            bot.reply_to(message, f"You do not own any stocks of {company}.")
    except Exception as e:
        bot.reply_to(message, f"An error occurred: {str(e)}")
