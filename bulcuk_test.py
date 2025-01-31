import datetime
import pytz
import dataset
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Set up logging so we get useful log statements in the terminal.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states for setup (/start) and logging (/log)
# Setup conversation states
BOOK_NAME, TOTAL_PAGES, PAGES_TO_READ, NOTIFICATION_TIME, TIMEZONE = range(5)
# Log conversation states
LOG_PAGES, LOG_NOTE = range(5, 7)

# Connect to the database (SQLite using dataset)
db = dataset.connect('sqlite:///books.db')


# -------------------------
# Setup /start Conversation
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Starting conversation for book setup for chat_id: %s", update.effective_chat.id)
    await update.message.reply_text(
        "Welcome! Let's set up your book info.\n\nWhat is the name of the book?"
    )
    return BOOK_NAME


async def book_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['book_name'] = update.message.text
    logger.info("Received book name: %s", update.message.text)
    await update.message.reply_text("How many pages does the book have?")
    return TOTAL_PAGES


async def total_pages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        total = int(update.message.text)
        context.user_data['total_pages'] = total
        logger.info("Received total pages: %d", total)
    except ValueError:
        await update.message.reply_text("Please enter a valid number for total pages.")
        return TOTAL_PAGES

    await update.message.reply_text("How many pages do you want to read per day?")
    return PAGES_TO_READ


async def pages_to_read(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        pages = int(update.message.text)
        context.user_data['pages_to_read'] = pages
        logger.info("Received pages to read per day: %d", pages)
    except ValueError:
        await update.message.reply_text("Please enter a valid number for pages to read.")
        return PAGES_TO_READ

    await update.message.reply_text(
        "At what time would you like to be reminded daily? "
        "Please send the time in HH:MM format (24-hour)."
    )
    return NOTIFICATION_TIME


async def notification_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    time_str = update.message.text.strip()
    try:
        notif_time = datetime.datetime.strptime(time_str, "%H:%M").time()
        context.user_data['notif_time'] = notif_time
        logger.info("Received notification time: %s", notif_time.strftime("%H:%M"))
    except ValueError:
        await update.message.reply_text("Invalid time format. Please use HH:MM (24-hour).")
        return NOTIFICATION_TIME

    await update.message.reply_text(
        "Please enter your timezone in IANA format (e.g., 'Europe/London' or 'America/New_York')."
    )
    return TIMEZONE


async def timezone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tz_input = update.message.text.strip()
    try:
        user_tz = pytz.timezone(tz_input)
        context.user_data['timezone'] = tz_input
        logger.info("Received timezone: %s", tz_input)
    except pytz.UnknownTimeZoneError:
        await update.message.reply_text(
            "Unknown timezone. Please enter a valid timezone (e.g., 'Europe/London')."
        )
        return TIMEZONE

    chat_id = update.effective_chat.id
    notif_time = context.user_data['notif_time']  # naive time entered by the user

    # Combine today's date with the user's notification time in their timezone
    local_dt = user_tz.localize(datetime.datetime.combine(datetime.date.today(), notif_time))
    # Convert to UTC – our server (and JobQueue) is assumed to work in UTC
    utc_dt = local_dt.astimezone(pytz.utc)
    utc_time = utc_dt.time()

    # Save or update the user settings in the database.
    users_table = db['users']
    users_table.upsert({
        'chat_id': chat_id,
        'book_name': context.user_data['book_name'],
        'total_pages': context.user_data['total_pages'],
        'pages_to_read': context.user_data['pages_to_read'],
        'notification_time': notif_time.strftime("%H:%M"),
        'timezone': tz_input,
    }, ['chat_id'])
    logger.info("User settings saved for chat_id: %s", chat_id)

    # Remove any existing job for this chat to avoid duplicate reminders.
    current_jobs = context.application.job_queue.get_jobs_by_name(str(chat_id))
    for job in current_jobs:
        job.schedule_removal()
        logger.info("Removed existing job for chat_id: %s", chat_id)

    # Schedule a daily reminder using the computed UTC time.
    context.application.job_queue.run_daily(
        send_reminder,
        time=utc_time,
        chat_id=chat_id,
        name=str(chat_id)
    )
    logger.info("Scheduled daily reminder for chat_id: %s at UTC time: %s", chat_id, utc_time.strftime("%H:%M"))

    reply = (
        "Your settings have been saved:\n"
        f"Book Name: {context.user_data['book_name']}\n"
        f"Total Pages: {context.user_data['total_pages']}\n"
        f"Pages to Read Daily: {context.user_data['pages_to_read']}\n"
        f"Daily Reminder at: {context.user_data['notif_time'].strftime('%H:%M')} ({tz_input})"
    )
    await update.message.reply_text(reply)
    return ConversationHandler.END


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """This function is called by the JobQueue to send daily reminders."""
    job = context.job
    chat_id = job.chat_id
    users_table = db['users']
    user = users_table.find_one(chat_id=chat_id)
    if user:
        book_name = user.get('book_name', 'your book')
        pages_to_read = user.get('pages_to_read', 'some')
        message = (
            f"Reminder: It's time to read '{book_name}'. "
            f"Try to read {pages_to_read} pages today!"
        )
        logger.info("Sending reminder to chat_id: %s", chat_id)
        await context.bot.send_message(chat_id, text=message)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END


# -------------------------
# Reading Log Conversation (/log)
# -------------------------
async def log_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Starting reading log for chat_id: %s", update.effective_chat.id)
    await update.message.reply_text("How many pages did you read today?")
    return LOG_PAGES


async def log_pages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        pages = int(update.message.text)
        context.user_data['pages_read'] = pages
        logger.info("Logged pages read: %d", pages)
    except ValueError:
        await update.message.reply_text("Please enter a valid number for pages read.")
        return LOG_PAGES

    await update.message.reply_text("Please enter a note on what you read today.")
    return LOG_NOTE


async def log_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    note = update.message.text
    chat_id = update.effective_chat.id
    log_date = datetime.datetime.utcnow().date().isoformat()

    logs_table = db['reading_logs']
    logs_table.insert({
        'chat_id': chat_id,
        'log_date': log_date,
        'pages_read': context.user_data.get('pages_read'),
        'note': note,
    })
    logger.info("Recorded reading log for chat_id: %s on %s", chat_id, log_date)
    await update.message.reply_text("Your reading progress has been recorded.")
    return ConversationHandler.END


# -------------------------
# Main Function
# -------------------------
def main():
    # Build the Application (replaces Updater/dispatcher)
    application = ApplicationBuilder().token("7824308233:AAFKBgHaIJH0OQ6kY7WAALm--G2lWvp65vQ").build()

    # Setup Conversation Handler for /start
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            BOOK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, book_name)],
            TOTAL_PAGES: [MessageHandler(filters.TEXT & ~filters.COMMAND, total_pages)],
            PAGES_TO_READ: [MessageHandler(filters.TEXT & ~filters.COMMAND, pages_to_read)],
            NOTIFICATION_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, notification_time)],
            TIMEZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, timezone_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(conv_handler)

    # Conversation Handler for /log
    log_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('log', log_start)],
        states={
            LOG_PAGES: [MessageHandler(filters.TEXT & ~filters.COMMAND, log_pages)],
            LOG_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, log_note)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(log_conv_handler)

    # ---------------------------------------------
    # Re-schedule daily reminder jobs from the database
    # ---------------------------------------------
    users_table = db['users']
    for user in users_table.all():
        try:
            chat_id = user['chat_id']
            notif_time_str = user['notification_time']  # stored as "HH:MM"
            tz_str = user['timezone']
            user_tz = pytz.timezone(tz_str)
            notif_time = datetime.datetime.strptime(notif_time_str, "%H:%M").time()
            local_dt = user_tz.localize(datetime.datetime.combine(datetime.date.today(), notif_time))
            utc_dt = local_dt.astimezone(pytz.utc)
            utc_time = utc_dt.time()

            for job in application.job_queue.get_jobs_by_name(str(chat_id)):
                job.schedule_removal()
                logger.info("Removed duplicate job for chat_id: %s", chat_id)

            application.job_queue.run_daily(
                send_reminder,
                time=utc_time,
                chat_id=chat_id,
                name=str(chat_id)
            )
            logger.info("Rescheduled daily reminder for chat_id: %s at UTC time: %s", chat_id, utc_time.strftime("%H:%M"))
        except Exception as e:
            logger.exception("Error scheduling job for chat_id %s: %s", user['chat_id'], e)

    # Run the bot using polling.
    application.run_polling()


if __name__ == '__main__':
    main()
