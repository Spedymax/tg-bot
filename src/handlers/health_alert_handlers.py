"""
Health Alert Button Handlers
Handles interactive button callbacks from health monitoring alerts
"""

import json
import time
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class HealthAlertHandlers:
    def __init__(self, bot):
        """Initialize health alert handlers"""
        self.bot = bot
        self.alert_history_file = '/home/spedymax/scripts/health_alerts/alert_history.json'

    def setup_handlers(self):
        """Set up health alert callback handlers"""

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("health_"))
        def health_alert_callback(call):
            """Handle interactive button callbacks from health monitoring alerts"""

            # Parse callback data: health_action_botname_issuetype
            # Example: health_snooze_main-bot_process_down
            parts = call.data.split('_', 3)
            if len(parts) < 4:
                self.bot.answer_callback_query(call.id, "Invalid button data")
                return

            action = parts[1]  # snooze, maintenance, resolved
            bot_name = parts[2]
            issue_type = parts[3]

            alert_key = f"{bot_name}:{issue_type}"

            # Load current state
            try:
                with open(self.alert_history_file, 'r') as f:
                    history = json.load(f)
            except:
                history = {}

            if alert_key not in history:
                history[alert_key] = {}

            alert = history[alert_key]
            timestamp = int(time.time())
            user_name = call.from_user.first_name or call.from_user.username or str(call.from_user.id)

            # Handle different actions
            if action == 'snooze':
                alert['snoozed'] = True
                alert['dismiss_until'] = timestamp + (24 * 3600)  # 24 hours
                alert['snoozed_by'] = user_name
                alert['snoozed_at'] = timestamp
                self.bot.answer_callback_query(call.id, "🔕 Snoozed for 24 hours")
                updated_text = f"{call.message.text}\n\n🔕 <b>Snoozed</b> by {user_name} for 24 hours"

            elif action == 'maintenance':
                alert['marked_maintenance'] = True
                alert['marked_maintenance_at'] = timestamp
                alert['marked_maintenance_by'] = user_name
                alert['dismiss_until'] = timestamp + (30 * 24 * 3600)  # 30 days
                self.bot.answer_callback_query(call.id, "⏸️ Maintenance mode (30 days)")
                updated_text = f"{call.message.text}\n\n⏸️ <b>Maintenance Mode</b> by {user_name}\n🔕 Suppressed for 30 days"

            elif action == 'resolved':
                alert['marked_resolved'] = True
                alert['marked_resolved_at'] = timestamp
                alert['marked_resolved_by'] = user_name
                alert['alert_count'] = 0
                # Clear all suppression flags
                alert.pop('snoozed', None)
                alert.pop('marked_maintenance', None)
                alert.pop('dismissed', None)
                alert.pop('acknowledged', None)
                alert.pop('dismiss_until', None)
                self.bot.answer_callback_query(call.id, "✓ Marked as resolved")
                updated_text = f"{call.message.text}\n\n✓ <b>Resolved</b> by {user_name} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            else:
                self.bot.answer_callback_query(call.id, "Unknown action")
                return

            # Save updated history
            try:
                os.makedirs(os.path.dirname(self.alert_history_file), exist_ok=True)
                with open(self.alert_history_file, 'w') as f:
                    json.dump(history, f, indent=2)
                logger.info(f"Health alert {action} by {user_name} for {alert_key}")
            except Exception as e:
                logger.error(f"Failed to save alert history: {e}")

            # Edit message to show status (remove buttons after interaction)
            try:
                self.bot.edit_message_text(
                    text=updated_text,
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Failed to edit health alert message: {e}")
