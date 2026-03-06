import re
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import json

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
CREDS_JSON = os.getenv("{
  "type": "service_account",
  "project_id": "telegram-trade-bot-489404",
  "private_key_id": "1ef97ca98723e999c1ca1b7f1cb24bae5b59d4af",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC2nc/la5QkHSKz\nghbQJmixpQOBH0Dsg1/clYD5K5zEfMUuqrMwjvChiu8ncEGfp+iM7pnazWdWgK/k\nGPvu8XuUhsjn71ZB0KnXVAUEuOYDgrAlNUCMA+suHjrqZdacKHgWPZe5GPz0TLSL\nPhgFEqBCm0NMUDIF+cDbKIj8paUiachOJ7kXQMwa8miY673w5q5aakuVk2D24PK1\n14vD4Ppg+b5Swi4AeVUQ/CdPf1R5uaTjBMjrm7t3nEhzDCF6amIrGcYSwg0toY8J\nNfPNfPitbU0LsaBty0LHhb+D2gS1BRAXUjk8NGGMY8XvsMMJgzBzrBFVzxelLixZ\nOIj5HN7JAgMBAAECggEAQqKvO73Xnp3rDamIfYemaDwYXUN0Q1lk327GUyWw3JnS\nscakADIIaEn0HmX97C4u0041YfvVm2D1zbu4ImaHe5j7MnbI+NcVQndsJV76v4ku\nkUUvOmgrpvZs9R8YAn9Z4nOzK12M3/AlaTHNPfyf8e4Jzozs0/VghBf0dIxVB4sH\nypsdQxaxddrPyR6Pp6uvCCPkXuGdu2Uv3dCJ7xP/ZuuZgdsx14HDopmm1O4uSPEO\nL4/kkKTkqqz+lmwi99PlG01kBw7p8/do2YsCIB58zSqxpu8uqyyXN8D7bjDUZghz\nYW+zS7t0qpENlc0tgr7JSXQFTSqKAlf7rVRU42IqqQKBgQDo8wYXQXMsXEUDAvRx\n3cZnHDe+OmiT7oYtUClMHSL8baKSWIAvV5IlvW9hS896Sqcqp78AXu2ua+xu3Z8t\niXUGVa2TeHf70yWhE0onfxQH8oM0eJnvAzSaE5tTZm3VqqvPPkCwgEtdnVLQq1DB\nwmFfGCeORiulHvDn3KrOKEXrIwKBgQDIr8brT/KzSU30ZD+GwdbVlDEXP/97V6tC\nZlcMVeYGDh0f4v+739L2KFoflnwc0kRD4t6g3vbqr+fYWSCMBGky0hPNf+btrMUO\nuq5VVwgXw60ycSCVG8O+jwujVx6xyEofaBj0oBcr0g8CFSLi+8P6KZjHeZO9v/X+\nRNg2hq9zIwKBgEKNzFuwk1tFMWJe4b/2gMzMvxBWV7KMH0Gq+WGJoYlFOYFeT6E2\n/8ZQjRXbNvfVhFUnf+Z3OKjwpKg4IVY9Q3X/3IuZi44jEUkn3bPTFsH+g4XmPvSO\nkeTDXUlCpna5QEUBoDHNNbsVS6faikQRaQhmOkbnvWh7opBb92DXGMLJAoGAEona\nUEZ0Xwd4ggj4rVQeqmAkIMeyrAwvL9UQWX1d4FVRb26ivRIyBLc5jA10rZzm3XaJ\npkayfH9/ZUbmcMi/hwhM+ADGrlH1aiTokc2WW8uhpjU5E00bSfEg3BfiJ/4eisQs\n+fwH5+5hoImfTWSAeA17pYGfmjmvWau2ZWMPtg0CgYEAt7MnsabQHykJ6urdKJ3Q\n+XMWX9SCkZc49a8HcUKAtM8sVzYl1dYS1w8Lj2dblLFYhXewmakcv0GuUgg37sm+\nkWWep24eq5J7r2VGANdAs24Uc7woQ0Hg7ENA7KV5BnGt4/rIr/yalJP1EkdgpPdR\nAII2ulZqnb9m+F2GfKNGehM=\n-----END PRIVATE KEY-----\n",
  "client_email": "telegram-trackerprofit-bot@telegram-trade-bot-489404.iam.gserviceaccount.com",
  "client_id": "113151832703232573900",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/telegram-trackerprofit-bot%40telegram-trade-bot-489404.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}")

scope = [
"https://spreadsheets.google.com/feeds",
"https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(CREDS_JSON)
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
        return int(config_sheet.acell("A1").value)
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

    rows = trade_sheet.col_values(8)

    for r in rows[1:]:
        processed_ids.add(r)

# -------------------------
# Save Trade
# -------------------------

def save_trade(trade,msg_id):

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

# -------------------------
# Read Trades
# -------------------------

def read_trades(days):

    rows = trade_sheet.get_all_values()

    total = 0
    count = 0

    for row in rows[1:]:

        try:

            date = datetime.fromisoformat(row[0])
            profit = float(row[6])

            if datetime.now(TH_TZ) - date <= timedelta(days=days):
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

# -------------------------
# Handle Message
# -------------------------

async def handle_message(update:Update,context:ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    text=update.message.text
    msg_id=update.message.message_id

    trade=process_trade(text)

    if trade:

        save_trade(trade,msg_id)
        print(f"Trade Saved: {trade}")

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
