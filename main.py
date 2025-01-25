import logging
import asyncio
import dataset
import random
import string
from telegram import Update
from datetime import datetime, time as datetime_time
from telegram.ext import (
    ApplicationBuilder, 
    ContextTypes, 
    CommandHandler, 
    MessageHandler, 
    ConversationHandler,
    filters
)
# from dotenv import load_dotenv
import os

# load_dotenv()
BOT_TOKEN = "7824308233:AAFKBgHaIJH0OQ6kY7WAALm--G2lWvp65vQ"
# BOT_TOKEN = os.getenv("BOT_TOKEN")
# import files
from bot_handlers import gen_referal_link, cancel, start, ask_pages, ask_pages_daily, get_book, ask_book, PAGES, BOOK, PAGES_DAILY, RECORD_METHOD, get_record_book
from bot_handlers import (
    NOTE,
    RECORD_NOTE,
    prompt_pages,
    get_note,
    record_note,
)

# ----- DATASET SETUP -----
# Connect to your local or remote database; this example uses a local SQLite file.
db = dataset.connect('sqlite:///bot_database.db')
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
def create_tables():
    if 'users' not in db.tables:
        db.create_table('users', primary_id='id', primary_type=db.types.integer)
    if 'book_info' not in db.tables:
        db.create_table('book_info', primary_id='user_id', primary_type=db.types.integer)
    if 'bet_pairs' not in db.tables:
        db.create_table('bet_pairs', primary_id='id', primary_type=db.types.integer)
    if 'daily_logs' not in db.tables:
        db.create_table('daily_logs', primary_id='id', primary_type=db.types.integer)
# functions:

if __name__ == '__main__':
    # Make sure tables exist
    create_tables()
    application = (
    ApplicationBuilder()
    .token(BOT_TOKEN)
    .concurrent_updates(True)  # Enable job queue
    .build()
)
    logging.info(f"BOT_TOKEN: {BOT_TOKEN}")
    # conv handlers
    conv_record_book_handler = ConversationHandler(
        entry_points=[CommandHandler("record_book", ask_book)],
        states={
            BOOK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_book)],
            PAGES: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_pages)],
            PAGES_DAILY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_pages_daily)],
            RECORD_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_record_book)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    conv_record_daily_log_handler = ConversationHandler(
        entry_points=[CommandHandler("record_daily_log", prompt_pages)],
        states={
            NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_note)],
            RECORD_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, record_note)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    # command handlers
    ref_link_handler = CommandHandler("generate_referal_link", gen_referal_link)
    start_command_handler = CommandHandler("start", start)
    # register handlers
    application.add_handler(conv_record_daily_log_handler)
    application.add_handler(conv_record_book_handler)
    application.add_handler(ref_link_handler)
    application.add_handler(start_command_handler)

    application.run_polling()