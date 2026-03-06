import re
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import json
import base64

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

TH_TZ = ZoneInfo("Asia/Bangkok")
TOKEN = os.getenv("TOKEN")

# -------------------------
# Google Sheet Setup
# -------------------------

SHEET_NAME = "CopyTradeTracker"
CREDS_B64 = os.getenv("GOOGLE_CREDS_B64")

scope = [
"https://spreadsheets.google.com/feeds",
"https://www.googleapis.com/auth/drive"
]

if CREDS_B64 is None:
    raise Exception("GOOGLE_CREDS_B64 not found in environment")

# decode base64 → json
creds_json = base64.b64decode(CREDS_B64).decode("utf-8")
creds_dict = json.loads(creds_json)

creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)

client = gspread.authorize(creds)
spreadsheet = client.open(SHEET_NAME)

trade_sheet = spreadsheet.worksheet("trades")
config_sheet = spreadsheet.worksheet("config")

# -------------------------
# Cache (FAST MODE)
# -------------------------

processed_ids = set()

# -------------------------
# Menu Keyboard
# -------------------------

keyboard = [
["📊 กำไรวันนี้"],
["📅 กำไรสัปดาห์นี้"],
["📈 กำไร 30 วัน"]
]

reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

thai_months = [
"มกราคม","กุมภาพันธ์","มีนาคม","เมษายน","พฤษภาคม","มิถุนายน",
"กรกฎาคม","สิงหาคม","กันยายน","ตุลาคม","พฤศจิกายน","ธันวาคม"
]

# -------------------------
# System Config
# -------------------------

def save_chat_id(cid):

    config_sheet.update("A1", [[cid]])

def get_chat_id():

    try:
        value = config_sheet.acell("A1").value

        if value:
            return int(value)

        return 0

    except:
        return 0

# -------------------------
# Utilities
# -------------------------

def thai_date():

    now = datetime.now(TH_TZ)

    return f"{now.day} {thai_months[now.month-1]} {now.year+543}"

# -------------------------
# Load Existing Trades
# -------------------------

def load_processed_ids():

    try:

        rows = trade_sheet.col_values(8)

        for r in rows[1:]:
            processed_ids.add(r)

        print("Loaded processed ids:", len(processed_ids))

    except Exception as e:

        print("Load processed id error:", e)

# -------------------------
# Save Trade
# -------------------------

def save_trade(trade,msg_id):

    try:

        if str(msg_id) in processed_ids:
            return

        trade_sheet.append_row([
            datetime.now(TH_TZ).isoformat(),
            trade["symbol"],
            trade["type"],
            trade["lot"],
            trade["open"],
            trade["close"],
            trade["profit"],
            msg_id
        ])

        processed_ids.add(str(msg_id))

    except Exception as e:

        print("Save trade error:", e)

# -------------------------
# Read Trades
# -------------------------

def read_trades(days):

    rows = trade_sheet.get_all_values()

    total = 0
    count = 0

    now = datetime.now(TH_TZ)

    for row in rows[1:]:

        try:

            date = datetime.fromisoformat(row[0])
            profit = float(row[6])

            if now - date <= timedelta(days=days):

                total += profit
                count += 1

        except:
            pass

    return total,count

# -------------------------
# Weekly Running Total
# -------------------------

def read_week_trades():

    rows = trade_sheet.get_all_values()

    now = datetime.now(TH_TZ)

    sunday = now - timedelta(days=(now.weekday()+1)%7)
    sunday = sunday.replace(hour=0,minute=0,second=0,microsecond=0)

    total = 0
    count = 0

    for row in rows[1:]:

        try:

            date = datetime.fromisoformat(row[0])
            profit = float(row[6])

            if date >= sunday:

                total += profit
                count += 1

        except:
            pass

    return total,count

# -------------------------
# Parse CopyTrade Message
# -------------------------

def process_trade(text):

    if "ปิดออเดอร์" not in text:
        return None

    symbol=re.search(r'([A-Z]{3,6}USD\.?[A-Z]*)',text)
    trade_type=re.search(r'\b(BUY|SELL)\b',text)
    lot=re.search(r'(\d+\.?\d*)\s*lot',text,re.IGNORECASE)

    open_price=re.search(r'ราคาเปิด[: ]\s*([\d,.]+)',text)
    close_price=re.search(r'ราคาปิด[: ]\s*([\d,.]+)',text)

    profit_match=re.search(r'(กำไร|ขาดทุน)[: ]\s*([+-]?\d+\.?\d*)',text)

    if not profit_match:
        return None

    value=float(profit_match.group(2))

    if profit_match.group(1)=="ขาดทุน":
        value=-abs(value)

    trade_data={

        "symbol":symbol.group(1) if symbol else "UNKNOWN",
        "type":trade_type.group(1) if trade_type else "UNKNOWN",
        "lot":float(lot.group(1)) if lot else 0,
        "open":float(open_price.group(1).replace(",","")) if open_price else 0,
        "close":float(close_price.group(1).replace(",","")) if close_price else 0,
        "profit":value
    }

    return trade_data

# -------------------------
# Menu
# -------------------------

async def menu(update:Update,context:ContextTypes.DEFAULT_TYPE):

    try:

        chat_id=update.effective_chat.id
        user_id=update.effective_user.id

        member=await context.bot.get_chat_member(chat_id,user_id)

        if member.status not in ["administrator","creator"]:
            return

        save_chat_id(chat_id)

        await update.message.reply_text(
            "📊 Copy Trade Profit Tracker",
            reply_markup=reply_markup
        )

    except Exception as e:

        print("Menu error:",e)

# -------------------------
# Handle Message
# -------------------------

async def handle_message(update:Update,context:ContextTypes.DEFAULT_TYPE):

    try:

        if not update.message:
            return

        text=update.message.text
        msg_id=update.message.message_id

        trade=process_trade(text)

        if trade:

            save_trade(trade,msg_id)
            print("Trade Saved:",trade)

        if text=="📊 กำไรวันนี้":

            total,count=read_trades(1)

            await update.message.reply_text(
                f"📊 วันนี้\n\nไม้:{count}\n\nกำไร:{round(total,2)} USD"
            )

        elif text=="📅 กำไรสัปดาห์นี้":

            total,count=read_week_trades()

            await update.message.reply_text(
                f"📅 สัปดาห์นี้ (สะสม)\n\nไม้:{count}\n\nกำไร:{round(total,2)} USD"
            )

        elif text=="📈 กำไร 30 วัน":

            total,count=read_trades(30)

            await update.message.reply_text(
                f"📈 30 วัน\n\nไม้:{count}\n\nกำไร:{round(total,2)} USD"
            )

    except Exception as e:

        print("Message error:",e)

# -------------------------
# Auto Reports
# -------------------------

async def send_thai_date(context):

    chat_id=get_chat_id()

    if chat_id==0:
        return

    await context.bot.send_message(chat_id=chat_id,text=f"📅 วันนี้\n{thai_date()}")

async def daily_report(context):

    chat_id=get_chat_id()

    if chat_id==0:
        return

    total,count=read_trades(1)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📊 สรุปวันนี้\nไม้:{count}\nกำไร:{round(total,2)} USD"
    )

async def weekly_report(context):

    chat_id=get_chat_id()

    if chat_id==0:
        return

    total,count=read_week_trades()

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📅 กำไรสะสมสัปดาห์นี้\nไม้:{count}\nกำไรสะสม:{round(total,2)} USD"
    )

# -------------------------
# Main
# -------------------------

def main():

    if TOKEN is None:
        print("TOKEN not found")
        return

    load_processed_ids()

    chat_id = get_chat_id()

    if chat_id != 0:
        print("Loaded Chat ID:", chat_id)

    app=ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("menu",menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_message))

    job_queue=app.job_queue

    job_queue.run_daily(send_thai_date,time=time(0,1,tzinfo=TH_TZ))
    job_queue.run_daily(daily_report,time=time(23,59,tzinfo=TH_TZ))
    job_queue.run_daily(weekly_report,time=time(23,59,tzinfo=TH_TZ))

    print("Copy Trade Tracker Running...")

    app.run_polling()

if __name__=="__main__":
    main()
