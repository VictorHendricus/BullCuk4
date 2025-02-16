import datetime
import uuid
import dataset
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# Database tables:
#   - users: chat_id, user_id, username, referrer, daily_pages, notif_time
#   - referrals: ref_code, chat_id, created_at
#   - daily_logs: chat_id, log_date, pages_read, note
#   - bets: user1, user2, start_date, status
users_table = db['users']
referrals_table = db['referrals']
daily_logs_table = db['daily_logs']
bets_table = db['bets']

# Conversation states
(SETUP_PAGES, SETUP_NOTIF_TIME) = range(2)
(DL_PAGES, DL_NOTE) = range(10, 12)
(SET_PAYMENT) = range(20)

# Helper function to parse time (assumed in HH:MM 24-hour format, UTC)
def parse_time(time_str: str) -> datetime.time:
    return datetime.datetime.strptime(time_str, "%H:%M").time()

# Schedule a daily reminder at the provided time (UTC)
async def schedule_daily_reminder(chat_id: int, notif_time: datetime.time, application):
    # Remove any existing job for this chat
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

# ---------------------------
# Setup Conversation (/start)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /start command initiates setup.
    It records basic user info and checks for a referral.
    Then it asks for the daily reading goal.
    """
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = update.message.text.split()
    ref_code = args[1] if len(args) > 1 else None

    # Insert user record if new.
    user_entry = users_table.find_one(chat_id=chat_id)
    if not user_entry:
        data = {
            'chat_id': chat_id,
            'user_id': user.id,
            'username': user.username,
        }
        if ref_code:
            ref_entry = referrals_table.find_one(ref_code=ref_code)
            if ref_entry:
                data['referrer'] = ref_entry['chat_id']
        users_table.insert(data)
        logger.info("New user recorded: chat_id %s", chat_id)
    else:
        logger.info("User exists: chat_id %s", chat_id)

    await update.message.reply_text("Welcome! How many pages do you want to read daily?")
    return SETUP_PAGES

async def setup_pages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Records the daily reading goal and asks for the notification time.
    """
    try:
        pages = int(update.message.text.strip())
        context.user_data['daily_pages'] = pages
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return SETUP_PAGES

    await update.message.reply_text(
        "At what time (HH:MM, 24-hour format) would you like to receive daily notifications? (UTC)"
    )
    return SETUP_NOTIF_TIME

async def setup_notif_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Records the notification time, updates user settings,
    creates a bet with status 'started' if a referrer exists,
    schedules the daily reminder, and shows the main menu.
    """
    try:
        notif_time = parse_time(update.message.text.strip())
        context.user_data['notif_time'] = notif_time
    except ValueError:
        await update.message.reply_text("Invalid time format. Please use HH:MM (24-hour).")
        return SETUP_NOTIF_TIME

    chat_id = update.effective_chat.id
    users_table.upsert({
        'chat_id': chat_id,
        'daily_pages': context.user_data['daily_pages'],
        'notif_time': notif_time.strftime("%H:%M"),
    }, ['chat_id'])

    # If the user has a referrer, create a bet record with status "started".
    user_entry = users_table.find_one(chat_id=chat_id)
    if user_entry and user_entry.get('referrer'):
        referrer = user_entry['referrer']
        existing_bet = bets_table.find_one(user1=referrer, user2=chat_id) or bets_table.find_one(user1=chat_id, user2=referrer)
        if not existing_bet:
            bets_table.insert({
                'user1': referrer,
                'user2': chat_id,
                'start_date': datetime.datetime.utcnow().isoformat(),
                'status': "started"
            })
            logger.info("Bet started between %s and %s", referrer, chat_id)

    await schedule_daily_reminder(chat_id, notif_time, context.application)

    # Show main menu with inline keyboard buttons.
    keyboard = [
        [InlineKeyboardButton("Generate Referral Link", callback_data="ref_link")],
        [InlineKeyboardButton("View Bet Status", callback_data="bet_status")],
        [InlineKeyboardButton("Log Daily Reading", callback_data="daily_log")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Setup complete! You'll receive daily reminders at your chosen time.", reply_markup=reply_markup)
    return ConversationHandler.END

# ---------------------------
# Daily Log Conversation (/daily_log)
async def daily_log_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the daily log conversation by asking for pages read."""
    await update.message.reply_text("How many pages did you read today?")
    return DL_PAGES

async def dl_pages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Records the number of pages read and asks for an optional note."""
    try:
        pages_read = int(update.message.text.strip())
        context.user_data['pages_read'] = pages_read
    except ValueError:
        await update.message.reply_text("Please enter a valid number for pages.")
        return DL_PAGES

    await update.message.reply_text("Would you like to add a note for today's reading? (Type your note or 'skip')")
    return DL_NOTE

async def dl_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Records the note (if provided) and upserts the daily log for the day."""
    note = update.message.text.strip()
    if note.lower() == "skip":
        note = ""
    chat_id = update.effective_chat.id
    log_date = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    try:
        daily_logs_table.upsert({
            'chat_id': chat_id,
            'log_date': log_date,
            'pages_read': context.user_data.get('pages_read', 0),
            'note': note
        }, ['chat_id', 'log_date'])
        await update.message.reply_text("Daily log recorded.")
    except Exception as e:
        logger.exception("Error recording daily log for chat_id %s: %s", chat_id, e)
        await update.message.reply_text("Error recording your log.")
    return ConversationHandler.END

# ---------------------------
# Referral Link Handler
async def ref_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates and sends a referral link."""
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
        if query:
            await query.answer()
            await query.edit_message_text("Error generating referral link.")
        else:
            await update.message.reply_text("Error generating referral link.")

# Add this new function for starting payment conversation
async def start_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Please enter your bet payment amount in USD like: "15"')
    return SET_PAYMENT

async def set_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    payment_amount = int(update.message.text)
    # Find the bet where the user is either user1 or user2
    bet = bets_table.find_one(user1=user_id) or bets_table.find_one(user2=user_id)
    if bet:
        bet_id = bet['id']
        bets_table.update({
            'id': bet_id,
            'payment_amount(USD)': payment_amount
        }, ['id'])
    await update.message.reply_text(f'Your bet payment amount has been set to {payment_amount} USD.')
    return ConversationHandler.END

# ---------------------------
# Bet Status Handler
async def bet_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the bet status for the user."""
    query = update.callback_query
    chat_id = update.effective_chat.id
    bet = bets_table.find_one(user1=chat_id) or bets_table.find_one(user2=chat_id)
    if bet:
        partner = bet['user2'] if bet['user1'] == chat_id else bet['user1']
        partner_rec = users_table.find_one(chat_id=partner)
        partner_name = partner_rec.get('username', str(partner)) if partner_rec else str(partner)
        text = f"Bet Active!\nYour partner: {partner_name}\nStart Date: {bet.get('start_date')}\nStatus: {bet.get('status', 'unknown')}"
    else:
        text = "No bet found."
    if query:
        await query.answer()
        await query.edit_message_text(text=text)
    else:
        await update.message.reply_text(text)

# ---------------------------
# Stop Bet Command
async def stop_bet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Stops the active bet by notifying both participants and updating the bet status.
    Optionally, stops the bot process entirely.
    """
    chat_id = update.effective_chat.id

    # Look for an active bet where the user is involved.
    bet = bets_table.find_one(user1=chat_id) or bets_table.find_one(user2=chat_id)
    if not bet:
        await update.message.reply_text("No active bet found.")
        return

    # Determine the partner's chat_id.
    partner_chat_id = bet['user2'] if bet['user1'] == chat_id else bet['user1']

    # Update the bet record to indicate that it has been stopped.
    bets_table.update({'status': 'stopped'}, ['user1', 'user2'])

    # Notify both participants.
    try:
        await context.bot.send_message(chat_id, text="Your bet has been stopped.")
        await context.bot.send_message(partner_chat_id, text="Your bet has been stopped.")
    except Exception as e:
        logger.exception("Error notifying bet participants: %s", e)

    # Optionally, to completely stop the bot, uncomment the following line:
    # await context.application.stop()


# ---------------------------
# Inline Keyboard Button Handler
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline keyboard button presses."""
    query = update.callback_query
    if query.data == "ref_link":
        await ref_link_handler(update, context)
    elif query.data == "bet_status":
        await bet_status_handler(update, context)
    elif query.data == "daily_log":
        await query.answer()
        await query.edit_message_text("To log your daily reading, please use the /daily_log command.")
    else:
        await query.answer("Unknown action.")

async def show_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Generate Referral Link", callback_data="ref_link")],
        [InlineKeyboardButton("View Bet Status", callback_data="bet_status")],
        [InlineKeyboardButton("Log Daily Reading", callback_data="daily_log")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Main Menu:", reply_markup=reply_markup)

# ---------------------------
# Main Function
def main():
    # Replace YOUR_BOT_TOKEN with your actual bot token.
    application = ApplicationBuilder().token("7824308233:AAFKBgHaIJH0OQ6kY7WAALm--G2lWvp65vQ").build()

    # Setup conversation handler for /start.
    setup_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SETUP_PAGES: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_pages)],
            SETUP_NOTIF_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_notif_time)],
        },
        fallbacks=[CommandHandler('cancel', lambda update, context: update.message.reply_text("Operation cancelled."))],
    )
    application.add_handler(setup_conv_handler)

    # Daily log conversation handler for /daily_log.
    daily_log_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('daily_log', daily_log_start)],
        states={
            DL_PAGES: [MessageHandler(filters.TEXT & ~filters.COMMAND, dl_pages)],
            DL_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, dl_note)],
        },
        fallbacks=[CommandHandler('cancel', lambda update, context: update.message.reply_text("Operation cancelled."))],
    )
    payment_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('set_payment', start_payment)],
        states={
            SET_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_payment)],
        },
        fallbacks=[CommandHandler('cancel', lambda update, context: update.message.reply_text("Operation cancelled."))],
    )
    application.add_handler(daily_log_conv_handler)
    application.add_handler(payment_conv_handler)
    application.add_handler(CommandHandler('ref_link', ref_link_handler))
    application.add_handler(CommandHandler('commands', show_commands))
    application.add_handler(CommandHandler('stop_bet', stop_bet))

    # Inline keyboard callback query handler.
    application.add_handler(CallbackQueryHandler(button_handler))

    # Global error handler.
    application.add_error_handler(error_handler)

    # Reschedule daily reminders for all users on startup.
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
                logger.info("Rescheduled reminder for chat_id %s", chat_id)
            except Exception as e:
                logger.exception("Error rescheduling reminder for chat_id %s: %s", user['chat_id'], e)

    application.run_polling()

if __name__ == '__main__':
    main()
