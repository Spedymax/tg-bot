# 🎰 Slot Machine Casino Mini-App

A beautiful web-based slot machine mini-app for your Telegram bot featuring emoji-based reels, 3-in-a-row winning mechanics, daily limits and BTC rewards.

## 🎯 Features

- **3-Reel Slot Machine**: Classic slot machine with 7 different emoji symbols
- **3-in-a-Row Wins**: Win only when you get three matching symbols
- **Daily Limits**: Players can spin 6 times per day (resets at midnight UTC)
- **Progressive Payouts**: From 3 BTC to 100 BTC jackpot
- **Animated Reels**: Smooth spinning animations with realistic physics
- **Jackpot Effects**: Special visual effects for big wins (50+ BTC)
- **Responsive Design**: Works perfectly on mobile devices
- **Real-time Integration**: Seamlessly integrates with your Telegram bot
- **Retro Casino UI**: Authentic slot machine design with metal effects

## 🚀 Quick Start

### Prerequisites

- Python 3.7+
- Flask
- Access to your main bot's database

### Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure the app:**
   - Update `web_app_url` in `miniapp_handlers.py` with your actual domain
   - Modify database connection settings in `app.py` if needed

3. **Run the mini-app:**
   ```bash
   python start_miniapp.py
   ```

4. **Access the app:**
   - Local: http://localhost:5000
   - Network: http://0.0.0.0:5000

## 🎮 How to Play

1. **Launch the Mini-App**: Use `/casino_app` command in your Telegram bot
2. **Check Status**: Use `/casino_status` to see remaining spins
3. **Spin the Wheel**: Click the "КРУТИТЬ КОЛЕСО" button
4. **Win Prizes**: Earn BTC, double your coins, or get bonus rewards
5. **Daily Reset**: Spins reset at midnight UTC

## 🏆 Prize Structure

| Combination | Payout | Probability | Description |
|-------------|--------|-------------|-------------|
| 💰💰💰 | 100 BTC | 1% | JACKPOT! |
| 💎💎💎 | 50 BTC | 2% | Mega Win |
| ⭐⭐⭐ | 30 BTC | 3% | Super Prize |
| 🔔🔔🔔 | 20 BTC | 5% | Great Win |
| 🍒🍒🍒 | 10 BTC | 8% | Good Result |
| 🍋🍋🍋 | 5 BTC | 10% | Small Win |
| 🍉🍉🍉 | 3 BTC | 15% | Mini Prize |
| Mixed symbols | 0 BTC | 56% | Try again |

### Symbols
- 💰 Money Bag (Jackpot symbol)
- 💎 Diamond (High value)
- ⭐ Star (Medium-high value)
- 🔔 Bell (Medium value)
- 🍒 Cherry (Classic slot symbol)
- 🍋 Lemon (Low value)
- 🍉 Watermelon (Lowest value)

## 🔧 API Endpoints

### Player Data
```
GET /api/player/<player_id>
```
Returns player's current coins and remaining spins.

### Spin Wheel
```
POST /api/spin
Body: {"player_id": 123456}
```
Processes a wheel spin and returns the result.

### Save Progress
```
POST /api/save_progress
Body: {"player_id": 123456, "coins": 150, "spins_used": 3}
```
Saves player progress back to the main database.

### Health Check
```
GET /health
```
Returns server status and active player count.

## 🎨 UI Components

- **Animated Wheel**: Smooth CSS animations with realistic physics
- **Prize Display**: Visual feedback for wins and losses
- **Progress Tracking**: Real-time coin and spin counters
- **Loading States**: Elegant loading animations during spins
- **Responsive Layout**: Mobile-first design approach

## 🔐 Security Features

- **Input Validation**: All API endpoints validate input data
- **Error Handling**: Comprehensive error handling with user-friendly messages
- **Rate Limiting**: Daily spin limits prevent abuse
- **Data Persistence**: Secure storage of player progress

## 📱 Telegram Integration

The mini-app integrates with your Telegram bot through:

1. **Web App Buttons**: Launch the casino directly from chat
2. **Data Exchange**: Send results back to the bot
3. **Player Sync**: Synchronize coins and progress
4. **Status Commands**: Check daily limits and progress

## 🔄 Development Workflow

1. **Local Development**: Use `python start_miniapp.py` for testing
2. **API Testing**: Use tools like Postman or curl to test endpoints
3. **Integration Testing**: Test with your Telegram bot using test URLs
4. **Production Deploy**: Deploy to your preferred hosting platform

## 🚀 Deployment Options

### Option 1: VPS/Dedicated Server
```bash
# Install dependencies
pip install -r requirements.txt

# Run with gunicorn for production
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Option 2: Heroku
```bash
# Create Procfile
echo "web: gunicorn app:app" > Procfile

# Deploy to Heroku
git add .
git commit -m "Deploy casino mini-app"
git push heroku main
```

### Option 3: Docker
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

## 🛠️ Configuration

### Environment Variables
```bash
FLASK_ENV=production
FLASK_DEBUG=false
DATABASE_URL=your_database_url
SECRET_KEY=your_secret_key
```

### Bot Integration
Update the following in your main bot:

1. Add `miniapp_handlers.py` to your handlers
2. Update `main.py` to include mini-app handlers
3. Configure the web app URL in settings

## 📊 Monitoring

The mini-app includes built-in monitoring:

- **Health Check**: `/health` endpoint for uptime monitoring
- **Logging**: Comprehensive logging for debugging
- **Error Tracking**: Automatic error reporting and handling

## 🔧 Customization

### Modify Prizes
Edit the `prizes` array in `app.py`:
```python
prizes = [
    {'text': 'Custom Prize!', 'type': 'coins', 'value': 100, 'probability': 0.1},
    # Add more prizes...
]
```

### Change Styling
Edit the CSS in `casino.html`:
```css
.casino-container {
    background: your-custom-gradient;
    /* Your custom styles */
}
```

### Adjust Daily Limits
Modify `max_daily_spins` in `app.py`:
```python
'max_daily_spins': 10  # Change from 6 to 10
```

## 🐛 Troubleshooting

### Common Issues

1. **CORS Errors**: Add CORS headers if needed
2. **Database Connection**: Check your database configuration
3. **Telegram Integration**: Verify your bot token and webhook URL
4. **Mobile Responsiveness**: Test on various device sizes

### Debug Mode
Enable debug mode for development:
```python
app.run(debug=True)
```

## 📚 Documentation

- **Flask Documentation**: https://flask.palletsprojects.com/
- **Telegram Bot API**: https://core.telegram.org/bots/api
- **Telegram Web Apps**: https://core.telegram.org/bots/webapps

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support and questions:
- Create an issue on GitHub
- Check the troubleshooting section
- Review the API documentation

---

**Have fun spinning! 🎰✨**
