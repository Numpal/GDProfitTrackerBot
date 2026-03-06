import re
import csv
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

TH_TZ = ZoneInfo("Asia/Bangkok")
TOKEN = os.getenv("TOKEN")

DATA_FILE = "trades.csv"
CHAT_ID_FILE = "chat_id.txt"
LAST_MSG_FILE = "last_message_id.txt"

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
# File Safety
# -------------------------

def ensure_files():

    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE,"w",newline="",encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date","symbol","type","lot","open","close","profit","msg_id"])

    if not os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE,"w") as f:
            f.write("0")

    if not os.path.exists(LAST_MSG_FILE):
        with open(LAST_MSG_FILE,"w") as f:
            f.write("0")

# -------------------------
# Utilities
# -------------------------

def thai_date():

    now = datetime.now(TH_TZ)
    return f"{now.day} {thai_months[now.month-1]} {now.year+543}"

def save_chat_id(chat_id):

    with open(CHAT_ID_FILE,"w") as f:
        f.write(str(chat_id))

def get_chat_id():

    with open(CHAT_ID_FILE) as f:
        return int(f.read())

def get_last_msg_id():

    try:
        with open(LAST_MSG_FILE) as f:
            return int(f.read())
    except:
        return 0

def save_last_msg_id(msg_id):

    with open(LAST_MSG_FILE,"w") as f:
        f.write(str(msg_id))

# -------------------------
# Trade Duplicate Check
# -------------------------

def trade_exists(msg_id):

    try:
        with open(DATA_FILE,"r",encoding="utf-8") as f:

            reader = csv.reader(f)

            for row in reader:
                if len(row) > 7 and row[7] == str(msg_id):
                    return True

    except:
        pass

    return False

# -------------------------
# Save Trade
# -------------------------

def save_trade(trade,msg_id):

    if trade_exists(msg_id):
        return

    with open(DATA_FILE,"a",newline="",encoding="utf-8") as f:

        writer = csv.writer(f)

        writer.writerow([
            datetime.now(TH_TZ).isoformat(),
            trade["symbol"],
            trade["type"],
            trade["lot"],
            trade["open"],
            trade["close"],
            trade["profit"],
            msg_id
        ])

# -------------------------
# Read Trades
# -------------------------

def read_trades(days):

    total=0
    count=0

    try:

        with open(DATA_FILE,"r",encoding="utf-8") as f:

            reader=csv.reader(f)

            for row in reader:

                if row[0]=="date":
                    continue

                date=datetime.fromisoformat(row[0])
                profit=float(row[6])

                if datetime.now(TH_TZ)-date<=timedelta(days=days):

                    total+=profit
                    count+=1

    except:
        pass

    return total,count

# -------------------------
# Weekly Running Total
# -------------------------

def read_week_trades():

    now=datetime.now(TH_TZ)

    sunday=now-timedelta(days=(now.weekday()+1)%7)
    sunday=sunday.replace(hour=0,minute=0,second=0,microsecond=0)

    total=0
    count=0

    try:

        with open(DATA_FILE,"r",encoding="utf-8") as f:

            reader=csv.reader(f)

            for row in reader:

                if row[0]=="date":
                    continue

                date=datetime.fromisoformat(row[0])
                profit=float(row[6])

                if date>=sunday:

                    total+=profit
                    count+=1

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

    last_id=get_last_msg_id()

    if msg_id<=last_id:
        return

    trade=process_trade(text)

    if trade:

        save_trade(trade,msg_id)
        print(f"Trade Saved: {trade}")

    save_last_msg_id(msg_id)

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

    ensure_files()

    if TOKEN is None:
        print("TOKEN not found")
        return

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
