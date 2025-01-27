# generat referal link
import logging
import asyncio
import dataset
import random
import string
from telegram import Update
from datetime import datetime, time
from telegram.ext import (
    ApplicationBuilder, 
    ContextTypes, 
    CommandHandler, 
    MessageHandler, 
    ConversationHandler,
    filters
)
# import files
from database_functions import save_inviter, save_function, save_invitee, retrieve_value, update_function
# general functions
async def validate_number(input_text: str, update: Update, prompt: str):
    if not input_text.isdigit():
        await update.message.reply_text(f"That doesn't look like a number. {prompt}")
        return False
    return True

# ref link funtion
async def gen_referal_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inviter_id = update.message.from_user.id
    inviter_username = update.message.from_user.username or "UnknownUser"
    ref_code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))  # Генерируем уникальный код
    await asyncio.to_thread(save_inviter, inviter_id, inviter_username)
    
    invite_link = f"https://t.me/VictorHendricus_test_bot?start={ref_code}"
    await update.message.reply_text(f"Here is your invite link: {invite_link}")

    # Optional: a fallback/cancel command to stop the conversation
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Conversation cancelled.")
    return ConversationHandler.END
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args  # Get the arguments passed to /start
    ref_code = args[0] if args else None
    username = update.message.from_user.username or "UnknownUser"
    user_id = update.message.from_user.id
    context.user_data["user_id"] = user_id
    context.user_data["username"] = username
    user_info = {
        "user_id": user_id,
        "username": username
    }
    await asyncio.to_thread(save_function, user_info, "users", "user_id")
    if ref_code:
        await asyncio.to_thread(save_invitee, user_id, username, ref_code)
        inviter_username = retrieve_value(ref_code, "bet_pairs", "inviter_username")
        await update.message.reply_text(f"Welcome! You were invited by {inviter_username}.")
    await update.message.reply_text("Hello, I am a reading bet bot. To record a book, use the /record_book command.")

# CONV HANDLERS
BOOK, PAGES, PAGES_DAILY, RECORD_METHOD = range(4)
async def ask_book(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    username = context.user_data["username"]
    await update.message.reply_text(f"Hi, @{username}, what is the name of the book?")
    return BOOK

async def get_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    book_name = update.message.text
    context.user_data["book"] = book_name

    await update.message.reply_text("Great, how many pages does it have?")
    return PAGES

# Step 3: Ask for total pages
async def ask_pages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pages_str = update.message.text
    is_valid = await validate_number(pages_str, update, "Please enter a valid number.")
    if not is_valid:
        return PAGES_DAILY

    context.user_data["pages"] = int(pages_str)
    await update.message.reply_text("Great, how many pages do you want to read daily?")
    return PAGES_DAILY

# Step 4: Ask for daily pages
async def ask_pages_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data["username"]
    pages_daily = update.message.text

    is_valid = await validate_number(pages_daily, update, "Please enter a valid number.")
    if not is_valid:
        return PAGES_DAILY

    pages_daily = int(pages_daily)
    context.user_data["pages_daily"] = pages_daily
    pages = context.user_data["pages"]
    context.user_data["days_to_read"] = pages // pages_daily if pages_daily != 0 else 0

    
    await update.message.reply_text(
        f"Thank you, @{username}! I've recorded:\n"
        f"Book: {context.user_data['book']}\n"
        f"Total pages: {context.user_data['pages']}\n"
        f"Daily pages: {context.user_data['pages_daily']}\n"
        f"Days to read: {context.user_data['days_to_read']}"
    )
    # ask for recording method
    await update.message.reply_text(
        f"How would you like to record your progress?\n"
        f"How many pages you read or on what page are you on right now?\n"
        f'type "1" for recording pages\n'
        f'type "2" for recording page number'
    )
    return RECORD_METHOD
async def get_record_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    record_method = update.message.text
    if record_method not in ["1", "2"]:
        await update.message.reply_text("Please enter a valid number.")
        return RECORD_METHOD
    user_info = {
        "user_id": context.user_data["user_id"],
        "username": context.user_data["username"],
        "book": context.user_data["book"],
        "pages": context.user_data["pages"],
        "pages_daily": context.user_data["pages_daily"],
        "days_to_read": context.user_data["days_to_read"],
        "record_method": record_method
    }
    await asyncio.to_thread(save_function, user_info, "book_info", "user_id")
    await update.message.reply_text(f"Great, you are set")
    return ConversationHandler.END
# daily logs
NOTE, RECORD_NOTE = range(2)
async def prompt_pages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    goal = retrieve_value("user_id", user_id, "book_info", "pages")
    await update.message.reply_text(f"Please enter the number of pages you read today. By the way, your goal is to read {goal} pages.")
    return NOTE
    # Step to get note from user
async def get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
        pages_read = update.message.text
        is_valid = await validate_number(pages_read, update, "Please enter a valid number of pages.")
        if not is_valid:
            return NOTE
        context.user_data['pages_read'] = pages_read  
        await update.message.reply_text("What is your note on what you have read?")
        return RECORD_NOTE

    # Step to record note and date
async def record_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
        note = update.message.text
        user_id = update.message.from_user.id
        user_id = context.user_data.get('user_id')
        pages_read = context.user_data.get('pages_read')
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        user_info = {
            "user_id": user_id,
            "pages_read": pages_read,
            "note": note,
            "date": current_date
        }
        
        await asyncio.to_thread(update_function, user_info, "daily_logs", "user_id")
        await update.message.reply_text("Your reading progress and note have been recorded.")
        return ConversationHandler.END

