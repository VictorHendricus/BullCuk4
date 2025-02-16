# Telegram Bot Comprehensive Documentation

## 1. Overview

This bot is built using the Python Telegram Bot framework. Its primary functionality includes:
- **User Setup:** Collecting user reading goals and preferred notification time.
- **Daily Logging:** Allowing users to log daily reading progress.
- **Referral System:** Generating referral links and setting up bets between users.
- **Bet Management:** Initiating and stopping bets between users.
- **Reminder Scheduling:** Sending daily reminders to log reading progress.
- **Error Handling:** Centralized error reporting and logging.

The bot uses a SQLite database (via the `dataset` library) to store user information, referrals, daily logs, and bets. Logging is managed through Python's built-in `logging` module.

---

## 2. Architecture and File Structure

### 2.1 Main File
- **main3.py:** Contains the complete bot implementation including the setup, command handling, conversation flows, database interactions, and scheduling. All commands and functions are defined in this file.  
  (See citeturn0file0 for full source code.)

### 2.2 Database
The bot connects to a SQLite database (`books.db`) and maintains the following tables:
- **users:** Stores user details such as `chat_id`, `user_id`, `username`, `referrer`, `daily_pages` (reading goal), and `notif_time`.
- **referrals:** Contains referral codes (`ref_code`), associated `chat_id`, and the creation timestamp (`created_at`).
- **daily_logs:** Records daily reading logs with fields like `chat_id`, `log_date`, `pages_read`, and an optional `note`.
- **bets:** Manages bet records between users with fields for `user1`, `user2`, `start_date`, and `status`.

---

## 3. Command and Conversation Flow

### 3.1 Setup Conversation (`/start`)
- **Purpose:** Initialize a new user or update an existing user’s information.
- **Flow:**
  1. **User Identification:** On `/start`, the bot extracts basic user information (chat ID, user ID, and username). It also checks for an optional referral code passed as an argument.
  2. **Daily Reading Goal:** The user is asked, "How many pages do you want to read daily?" This input is recorded as the daily reading goal.
  3. **Notification Time:** The bot then prompts for a daily notification time in HH:MM (24-hour UTC). This value is parsed and stored.
  4. **Referral Bet Setup:** If a referral code is detected, the bot establishes a bet between the referrer and the new user by inserting a record in the bets table.
  5. **Scheduling Reminder:** A daily reminder is scheduled using the Telegram job queue.
  6. **Main Menu Display:** An inline keyboard is shown, offering options to generate a referral link, view bet status, or log daily reading.
  
  _Key Functions:_
  - `start()`
  - `setup_pages()`
  - `setup_notif_time()`
  
  (For details, see citeturn0file0.)

### 3.2 Daily Log Conversation (`/daily_log`)
- **Purpose:** To record the user’s daily reading progress.
- **Flow:**
  1. **Page Count Input:** The conversation begins with asking, "How many pages did you read today?" The response is stored.
  2. **Optional Note:** Users are then prompted to add an optional note about their reading. They can type a note or type "skip" to omit.
  3. **Database Update:** The bot records the daily log (including date, pages read, and note) in the `daily_logs` table.
  
  _Key Functions:_
  - `daily_log_start()`
  - `dl_pages()`
  - `dl_note()`
  
  (Refer to citeturn0file0 for the implementation.)

### 3.3 Referral Link Generation (`/ref_link`)
- **Purpose:** Allow users to generate a unique referral link that can be shared with others.
- **Flow:**
  1. **Referral Code Creation:** A unique referral code is generated using the `uuid` module.
  2. **Database Insertion:** The referral code is stored in the `referrals` table along with the user’s chat ID and a timestamp.
  3. **Link Generation:** The bot retrieves its username to create a deep-link URL which includes the referral code.
  4. **Output:** The generated referral link is sent to the user.
  
  _Key Function:_ `ref_link_handler()`
  
  (For complete details, see citeturn0file0.)

### 3.4 Bet Status and Management
- **Bet Status (`/bet_status`):**
  - **Purpose:** Display the status of a bet between two users.
  - **Flow:** The bot searches the `bets` table for a record involving the current user. If found, it displays the partner’s information, the start date, and the current bet status.
  - _Key Function:_ `bet_status_handler()`
  
- **Stop Bet (`/stop_bet`):**
  - **Purpose:** To stop an active bet.
  - **Flow:**
    1. **Check for Active Bet:** The bot verifies if an active bet exists for the user.
    2. **Update Status:** The bet's status is updated to "stopped" in the database.
    3. **Notification:** Both participants are notified that the bet has been stopped.
    4. **Optional Stop:** There is an option to completely stop the bot process (commented out in the code).
    
  - _Key Function:_ `stop_bet()`
  
  (Further details are available in citeturn0file0.)

### 3.5 Inline Keyboard Handler
- **Purpose:** Manage button presses from the inline keyboard shown in the main menu.
- **Flow:** Depending on the button pressed, the bot routes the user to:
  - Generate a referral link
  - View bet status
  - Receive instructions to log daily reading (redirecting to the `/daily_log` command)
  
  _Key Function:_ `button_handler()`
  
  (See citeturn0file0 for code specifics.)

### 3.6 Showing Commands (`/commands`)
- **Purpose:** Provides users with a main menu displaying available commands via an inline keyboard.
- **Key Function:** `show_commands()`

---

## 4. Scheduling and Reminders

### 4.1 Daily Reminder Scheduling
- **Functionality:** The bot schedules a daily reminder for each user at their specified notification time using the Telegram job queue.
- **Process:**
  1. **Schedule Setup:** In the `setup_notif_time()` function, after recording the user's notification time, a daily job is scheduled to send a reminder message.
  2. **Job Execution:** The `send_daily_reminder()` function is executed at the scheduled time, prompting the user to log their reading progress.
  3. **Rescheduling on Startup:** When the bot starts, it iterates over all users in the `users` table and re-schedules reminders based on stored notification times.
  
  _Key Functions:_
  - `schedule_daily_reminder()`
  - `send_daily_reminder()`
  
  (For detailed implementation, refer to citeturn0file0.)

---

## 5. Error Handling

### 5.1 Global Error Handler
- **Purpose:** To capture and log exceptions that occur during update handling.
- **Implementation:** The `error_handler()` function logs errors and attempts to notify the user with a generic message if an error occurs during message processing.
  
  _Key Function:_ `error_handler()`
  
  (Detailed error logging is visible in citeturn0file0.)

---

## 6. Logging and Debugging

- **Logging Setup:** Python’s `logging` module is used to log events, errors, and important actions (e.g., scheduling reminders, user registrations, bet management). The logs include timestamps, logger names, and severity levels.
- **Use Cases:** Logging helps in debugging issues such as failed database operations, scheduling errors, and bot command handling errors.

---

## 7. Main Function and Bot Execution

### 7.1 Application Initialization
- **Token Configuration:** The bot is initialized with a specific bot token using the `ApplicationBuilder`.
- **Handler Registration:** The main function registers multiple handlers:
  - **Conversation Handlers:** For `/start` and `/daily_log`.
  - **Command Handlers:** For `/ref_link`, `/commands`, and `/stop_bet`.
  - **CallbackQuery Handler:** For inline keyboard interactions.
  - **Global Error Handler:** To capture exceptions.
  
### 7.2 Startup Process
- **Rescheduling Reminders:** On startup, the bot re-schedules daily reminders for all users based on the stored notification time.
- **Polling:** The bot uses `application.run_polling()` to continuously check for and process updates.
  
  _Key Function:_ `main()`
  
  (The main execution flow is outlined in citeturn0file0.)

---

## 8. Usage Instructions

1. **Starting the Bot:**
   - Users start the bot by sending the `/start` command.
   - The bot then guides the user through setting up their daily reading goal and preferred notification time.
   
2. **Logging Daily Reading:**
   - To log daily reading progress, users should send the `/daily_log` command.
   - The bot will prompt for the number of pages read and an optional note.

3. **Referral System:**
   - Users can generate a referral link using the `/ref_link` command or via the inline keyboard.
   - When a referral code is used during setup, a bet is automatically initiated between the referrer and the new user.

4. **Checking Bet Status:**
   - Users can view the status of an active bet using the inline keyboard button for bet status or the `/bet_status` command.

5. **Stopping a Bet:**
   - The `/stop_bet` command is provided to allow users to stop an active bet, which updates the bet status and notifies both participants.

6. **Accessing Main Menu:**
   - The `/commands` command shows the main menu with all available actions presented via an inline keyboard.

---

