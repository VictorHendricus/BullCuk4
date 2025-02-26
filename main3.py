import datetime
import uuid
import dataset
import logging
import json
from bot_token import bot_token
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Connect to SQLite database
db = dataset.connect('sqlite:///books.db')

# Database tables
users_table = db['users']          # chat_id, user_id, username, referrer, daily_pages, notif_time, book_title, timezone
referrals_table = db['referrals']  # ref_code, chat_id, created_at
daily_logs_table = db['daily_logs'] # chat_id, log_date, pages_read, note, goal_completed, book_title
bets_table = db['bets']            # user1, user2, start_date, status, payment_amount(USD)

# Conversation states for daily log and payment
(DL_PAGES, DL_NOTE) = range(10, 12)
SET_PAYMENT = 20

# Helper function to parse time (HH:MM 24-hour format)
def parse_time(time_str: str) -> datetime.time:
    return datetime.datetime.strptime(time_str, "%H:%M").time()

# Helper function to convert local time to UTC based on timezone offset
def convert_to_utc(time_obj: datetime.time, timezone_offset: int) -> datetime.time:
    now = datetime.datetime.now()
    dt = datetime.datetime.combine(now.date(), time_obj)
    dt = dt - datetime.timedelta(hours=int(timezone_offset))
    return dt.time()

# Schedule a daily reminder
async def schedule_daily_reminder(chat_id: int, notif_time: datetime.time, application):
    for job in application.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()
    application.job_queue.run_daily(
        send_daily_reminder,
        time=notif_time,
        chat_id=chat_id,
        name=str(chat_id)
    )
    logger.info("Scheduled daily reminder for chat_id %s at %s", chat_id, notif_time.strftime("%H:%M"))

async def send_daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    try:
        await context.bot.send_message(
            chat_id,
            text="Daily Reminder: Please log your reading progress using /daily_log."
        )
    except Exception as e:
        logger.exception("Error sending daily reminder to chat_id %s: %s", chat_id, e)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and hasattr(update, 'message') and update.message:
        try:
            await update.message.reply_text("An unexpected error occurred.")
        except Exception:
            pass

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    ref_code = args[0] if args else None

    # Insert or update user record
    user_entry = users_table.find_one(chat_id=chat_id)
    if not user_entry:
        users_table.insert({
            'chat_id': chat_id,
            'user_id': user.id,
            'username': user.username,
        })
        logger.info("New user recorded: chat_id %s", chat_id)
    elif user_entry.get('daily_pages') and user_entry.get('notif_time'):
        await show_main_menu(update, context)
        return

    # Store referral code if present
    if ref_code:
        context.user_data['ref_code'] = ref_code

    # Prompt user to open web app for setup
    keyboard = [[InlineKeyboardButton("Open Setup", web_app=WebAppInfo(url="https://victorhendricus.github.io/BullCuk4/"))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Please complete your setup by clicking the button below.", reply_markup=reply_markup)

# Handle web app data
async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Web app data handler triggered")  # Debugging line
    try:
        # Log the raw data for debugging
        raw_data = update.message.web_app_data.data
        logger.info(f"Received web app data: {raw_data}")
        
        data = json.loads(raw_data)
        book_title = data['book_title']
        if not book_title or book_title.strip() == "":
            raise ValueError("Book title cannot be empty")
        
        pages = int(data['pages'])
        if pages <= 0:
            raise ValueError("Pages must be positive")
        
        time_str = data['time']
        timezone_offset = int(data['timezone'])
        
        # Parse local time
        local_time = parse_time(time_str)
        
        # Convert to UTC for storage and scheduling
        utc_time = convert_to_utc(local_time, timezone_offset)
        
        user_id = int(data['user_id'])
        if user_id != update.effective_user.id:
            raise ValueError("User ID mismatch")
            
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        logger.error(f"Error processing web app data: {e}")
        await update.message.reply_text(f"Invalid data: {e}. Please try again.")
        return

    try:
        # Store setup data
        users_table.upsert({
            'chat_id': chat_id,
            'daily_pages': pages,
            'notif_time': utc_time.strftime("%H:%M"),
            'book_title': book_title,
            'timezone': timezone_offset
        }, ['chat_id'])
        
        logger.info(f"Saved user setup: chat_id={chat_id}, book={book_title}, pages={pages}, time={utc_time.strftime('%H:%M')}, timezone={timezone_offset}")

        # Handle referral
        ref_code = context.user_data.get('ref_code')
        if ref_code:
            ref_entry = referrals_table.find_one(ref_code=ref_code)
            if ref_entry:
                referrer_chat_id = ref_entry['chat_id']
                users_table.update({
                    'chat_id': chat_id,
                    'referrer': referrer_chat_id
                }, ['chat_id'])
                existing_bet = bets_table.find_one(user1=referrer_chat_id, user2=chat_id) or \
                              bets_table.find_one(user1=chat_id, user2=referrer_chat_id)
                if not existing_bet:
                    bets_table.insert({
                        'user1': referrer_chat_id,
                        'user2': chat_id,
                        'start_date': datetime.datetime.utcnow().isoformat(),
                        'status': "started"
                    })
                    logger.info("Bet started between %s and %s", referrer_chat_id, chat_id)

        # Schedule reminder
        await schedule_daily_reminder(chat_id, utc_time, context.application)

        # Confirm and show menu
        tz_display = f"UTC{'+' if timezone_offset >= 0 else ''}{timezone_offset}"
        await update.message.reply_text(f"Setup complete for '{book_title}'! You'll receive daily reminders at {time_str} {tz_display}.")
        await show_main_menu(update, context)
        
    except Exception as e:
        logger.exception(f"Error saving setup data: {e}")
        await update.message.reply_text("An error occurred while saving your setup. Please try again.")

# Show main menu
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Generate Referral Link", callback_data="ref_link")],
        [InlineKeyboardButton("View Bet Status", callback_data="bet_status")],
        [InlineKeyboardButton("Log Daily Reading", callback_data="daily_log")],
        [InlineKeyboardButton("View/Change Book", callback_data="view_book")],
        [InlineKeyboardButton("Test Notification", callback_data="test_notif")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Main Menu:", reply_markup=reply_markup)

# Daily log conversation
async def daily_log_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    user = users_table.find_one(chat_id=chat_id)
    if not user or not user.get('daily_pages') or not user.get('notif_time'):
        await update.message.reply_text("Please complete your setup first by using /start.")
        return ConversationHandler.END
    
    book_title = user.get('book_title', 'Unknown Book')
    await update.message.reply_text(f"How many pages did you read today for '{book_title}'?")
    return DL_PAGES

async def dl_pages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        pages_read = int(update.message.text.strip())
        context.user_data['pages_read'] = pages_read
    except ValueError:
        await update.message.reply_text("Please enter a valid number for pages.")
        return DL_PAGES
    await update.message.reply_text("Would you like to add a note? (Type your note or 'skip')")
    return DL_NOTE

async def dl_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    note = update.message.text.strip()
    if note.lower() == "skip":
        note = ""
    chat_id = update.effective_chat.id
    log_date = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    try:
        user = users_table.find_one(chat_id=chat_id)
        if not user:
            await update.message.reply_text("Error: User not found. Please use /start.")
            return ConversationHandler.END
        daily_goal = user.get('daily_pages', 0)
        book_title = user.get('book_title', 'Unknown Book')
        pages_read = context.user_data.get('pages_read', 0)
        goal_completed = 'yes' if pages_read >= daily_goal else 'no'
        daily_logs_table.upsert({
            'chat_id': chat_id,
            'log_date': log_date,
            'pages_read': pages_read,
            'note': note,
            'goal_completed': goal_completed,
            'book_title': book_title
        }, ['chat_id', 'log_date'])
        await update.message.reply_text(f"Daily log recorded for '{book_title}'.")
    except Exception as e:
        logger.exception("Error recording daily log for chat_id %s: %s", chat_id, e)
        await update.message.reply_text("Error recording log. Please ensure setup is complete with /start.")
    return ConversationHandler.END

# Referral link handler
async def ref_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = update.effective_chat.id
    ref_code = str(uuid.uuid4())
    try:
        referrals_table.insert({
            'ref_code': ref_code,
            'chat_id': chat_id,
            'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={ref_code}"
        text = f"Share this referral link:\n{link}"
        if query:
            await query.answer()
            await query.edit_message_text(text=text)
        else:
            await update.message.reply_text(text)
    except Exception as e:
        logger.exception("Error generating referral link for chat_id %s: %s", chat_id, e)
        text = "Error generating referral link."
        if query:
            await query.answer()
            await query.edit_message_text(text)
        else:
            await update.message.reply_text(text)

# Payment conversation
async def start_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Please enter your bet payment amount in USD (e.g., "15")')
    return SET_PAYMENT

async def set_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    try:
        payment_amount = int(update.message.text)
        bet = bets_table.find_one(user1=user_id) or bets_table.find_one(user2=user_id)
        if bet:
            bets_table.update({
                'id': bet['id'],
                'payment_amount(USD)': payment_amount
            }, ['id'])
        await update.message.reply_text(f"Bet payment set to {payment_amount} USD.")
        await ref_link_handler(update, context)
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return SET_PAYMENT
    except Exception as e:
        logger.exception("Error setting payment for user_id %s: %s", user_id, e)
        await update.message.reply_text("Error setting payment.")
    return ConversationHandler.END

# Bet status handler
async def bet_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = update.effective_chat.id
    bet = bets_table.find_one(user1=chat_id) or bets_table.find_one(user2=chat_id)
    if bet:
        partner = bet['user2'] if bet['user1'] == chat_id else bet['user1']
        partner_rec = users_table.find_one(chat_id=partner)
        partner_name = partner_rec.get('username', str(partner)) if partner_rec else str(partner)
        text = f"Bet Active!\nPartner: {partner_name}\nStart Date: {bet.get('start_date')}\nStatus: {bet.get('status', 'unknown')}"
    else:
        text = "No bet found."
    if query:
        await query.answer()
        await query.edit_message_text(text=text)
    else:
        await update.message.reply_text(text)

# Stop bet command
async def stop_bet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    bet = bets_table.find_one(user1=chat_id) or bets_table.find_one(user2=chat_id)
    if not bet:
        await update.message.reply_text("No active bet found.")
        return
    partner_chat_id = bet['user2'] if bet['user1'] == chat_id else bet['user1']
    bets_table.update({'status': 'stopped'}, ['user1', 'user2'])
    try:
        await context.bot.send_message(chat_id, text="Your bet has been stopped.")
        await context.bot.send_message(partner_chat_id, text="Your bet has been stopped.")
    except Exception as e:
        logger.exception("Error notifying bet participants: %s", e)

# Button handler
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.data == "ref_link":
        await ref_link_handler(update, context)
    elif query.data == "bet_status":
        await bet_status_handler(update, context)
    elif query.data == "daily_log":
        await query.answer()
        await query.edit_message_text("Use /daily_log to log your reading.")
    elif query.data == "view_book":
        await query.answer()
        await view_book_setup(update, context)
    elif query.data == "test_notif":
        await query.answer()
        await test_notification(update, context)
    else:
        await query.answer("Unknown action.")

async def show_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Generate Referral Link", callback_data="ref_link")],
        [InlineKeyboardButton("View Bet Status", callback_data="bet_status")],
        [InlineKeyboardButton("Log Daily Reading", callback_data="daily_log")],
        [InlineKeyboardButton("View/Change Book", callback_data="view_book")],
        [InlineKeyboardButton("Test Notification", callback_data="test_notif")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Main Menu:", reply_markup=reply_markup)

# View current book setup
async def view_book_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = users_table.find_one(chat_id=chat_id)
    if not user or not user.get('book_title'):
        await update.message.reply_text("You haven't set up a book yet. Use /start to set up.")
        return
    
    book_title = user.get('book_title', 'Unknown Book')
    daily_pages = user.get('daily_pages', 0)
    notif_time = user.get('notif_time', 'Not set')
    timezone = user.get('timezone', 0)
    
    tz_display = f"UTC{'+' if int(timezone) >= 0 else ''}{timezone}"
    
    message = f"Current Book Setup:\n\nTitle: {book_title}\nDaily Goal: {daily_pages} pages\nReminder Time: {notif_time} {tz_display}"
    
    keyboard = [[InlineKeyboardButton("Change Book", web_app=WebAppInfo(url="https://victorhendricus.github.io/BullCuk4/"))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, reply_markup=reply_markup)

# Debug command to check database state
async def debug_db(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    
    # Only allow for specific users (replace with your chat_id)
    if chat_id != 123456789:  # Replace with your actual chat_id for testing
        await update.message.reply_text("Debug command not available.")
        return
    
    try:
        user = users_table.find_one(chat_id=chat_id)
        if user:
            user_info = f"User info:\n"
            for key, value in user.items():
                user_info += f"{key}: {value}\n"
            await update.message.reply_text(user_info)
        else:
            await update.message.reply_text("No user record found.")
            
        logs = list(daily_logs_table.find(chat_id=chat_id, order_by='-log_date', _limit=5))
        if logs:
            logs_info = f"\nRecent logs:\n"
            for log in logs:
                logs_info += f"{log['log_date']}: {log['pages_read']} pages, book: {log.get('book_title', 'Unknown')}\n"
            await update.message.reply_text(logs_info)
        else:
            await update.message.reply_text("No logs found.")
            
    except Exception as e:
        logger.exception(f"Error in debug command: {e}")
        await update.message.reply_text(f"Error: {e}")

# Test notification
async def test_notification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = users_table.find_one(chat_id=chat_id)
    
    if not user or not user.get('notif_time'):
        await update.message.reply_text("You haven't set up notifications yet. Use /start to set up.")
        return
    
    book_title = user.get('book_title', 'your book')
    notif_time = user.get('notif_time')
    timezone = user.get('timezone', 0)
    
    tz_display = f"UTC{'+' if int(timezone) >= 0 else ''}{timezone}"
    
    await update.message.reply_text(
        f"This is a test notification for '{book_title}'.\n\n"
        f"Your daily reminders are scheduled for {notif_time} {tz_display}.\n\n"
        f"Don't forget to log your reading progress using /daily_log."
    )

# Main function
def main():
    application = ApplicationBuilder().token(bot_token).build()

    # Daily log conversation handler
    daily_log_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('daily_log', daily_log_start)],
        states={
            DL_PAGES: [MessageHandler(filters.TEXT & ~filters.COMMAND, dl_pages)],
            DL_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, dl_note)],
        },
        fallbacks=[CommandHandler('cancel', lambda update, context: update.message.reply_text("Operation cancelled."))],
    )
    application.add_handler(daily_log_conv_handler)

    # Payment conversation handler
    payment_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('set_payment', start_payment)],
        states={
            SET_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_payment)],
        },
        fallbacks=[CommandHandler('cancel', lambda update, context: update.message.reply_text("Operation cancelled."))],
    )
    application.add_handler(payment_conv_handler)

    # Other handlers
    application.add_handler(CommandHandler('commands', show_commands))
    application.add_handler(CommandHandler('stop_bet', stop_bet))
    application.add_handler(CommandHandler('book', view_book_setup))
    application.add_handler(CommandHandler('debug', debug_db))
    application.add_handler(CommandHandler('test_notification', test_notification))
    application.add_handler(CallbackQueryHandler(button_handler))
    # Corrected filter for web app data
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    application.add_handler(CommandHandler('start', start))
    application.add_error_handler(error_handler)

    # Reschedule reminders on startup
    for user in users_table.all():
        if user.get('notif_time'):
            try:
                notif_time = parse_time(user['notif_time'])
                chat_id = user['chat_id']
                application.job_queue.run_daily(
                    send_daily_reminder,
                    time=notif_time,
                    chat_id=chat_id,
                    name=str(chat_id)
                )
                logger.info("Rescheduled reminder for chat_id %s at %s UTC", chat_id, notif_time.strftime("%H:%M"))
            except Exception as e:
                logger.exception("Error rescheduling reminder for chat_id %s: %s", user['chat_id'], e)

    application.run_polling()

if __name__ == '__main__':
    main()