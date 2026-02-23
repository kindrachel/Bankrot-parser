import asyncio
import aiohttp
import requests
import time
import json
import os
import base64
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfbase.ttfonts import TTFont
from aiohttp import web
import signal

# Импорт парсера (обязательный)
try:
    from parser_fedresurs import get_all_trades, TRUSTEE_NAMES, MIN_DATE
    PARSER_AVAILABLE = True
except ImportError:
    PARSER_AVAILABLE = False
    print("✗ Парсер недоступен. Установите: pip install selenium webdriver-manager")


# Загрузка переменных окружения
load_dotenv()

# Информация о заявителе
APPLICANT_BIRTH = os.getenv('APPLICANT_BIRTH')
SERIES = os.getenv('SERIES')
NUMBER = os.getenv('NUMBER')
APPLICANT_RES_ADDRESS = os.getenv('APPLICANT_RES_ADDRESS')
APPLICANT_INN = os.getenv('APPLICANT_INN')
APPLICANT_OGRNIP = os.getenv('APPLICANT_OGRNIP')
OGRNIP_BIRTH = os.getenv('OGRNIP_BIRTH')
APPLICANT_PHONE = os.getenv('APPLICANT_PHONE')
APPLICANT_EMAIL = os.getenv('APPLICANT_EMAIL')

# Настройки
API_URL = 'https://api-cloud.ru/api/bankrot.php'
TOKEN = os.getenv('API_TOKEN')
SEEN_FILE = 'seen_cases.json'
PENDING_LOTS_FILE = 'pending_lots.json'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL = os.getenv('EMAIL')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_TO = os.getenv('EMAIL_TO')
SMTP_SERVER = 'connect.smtp.bz'
SMTP_PORT = 587
TIMEOUT = 120

# Функция для загрузки просмотренных дел
def load_seen_cases():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f:
            return json.load(f)
    return []

# Функция для сохранения просмотренных дел
def save_seen_cases(seen_cases):
    with open(SEEN_FILE, 'w') as f:
        json.dump(seen_cases, f)

# Функция для загрузки ожидающих лотов
def load_pending_lots():
    if os.path.exists(PENDING_LOTS_FILE):
        with open(PENDING_LOTS_FILE, 'r') as f:
            return json.load(f)
    return {}

# Функция для сохранения ожидающих лотов
def save_pending_lots(pending_lots):
    with open(PENDING_LOTS_FILE, 'w') as f:
        json.dump(pending_lots, f)



# Асинхронная функция для получения деталей дела
async def get_case_details_async(session, guid):
    params = {
        'token': TOKEN,
        'type': 'getCase',
        'guid': guid
    }
    try:
        async with session.get(API_URL, params=params, timeout=TIMEOUT) as response:
            if response.status == 200:
                return await response.json()
            return None
    except Exception as e:
        print(f"Ошибка получения деталей для {guid}: {e}")
        return None

# Функция для отправки сообщения в Telegram
async def send_to_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram не настроен")
        return
    
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        print(f"✓ Отправлено в Telegram: {message[:50]}...")
    except TelegramBadRequest as e:
        print(f"✗ Ошибка Telegram: {e}")
    except Exception as e:
        print(f"✗ Ошибка отправки в Telegram: {e}")

# Функция для генерации PDF
def generate_pdf(trustee_name, case_info):
    pdfmetrics.registerFont(TTFont('SFPro', 'SFProText-Regular.ttf'))
    
    doc = SimpleDocTemplate("Заявка.pdf", pagesize=letter)
    styles = getSampleStyleSheet()
    
    # Создаем стили с поддержкой русского языка
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontName='SFPro',
        fontSize=16,
        alignment=TA_CENTER,
        spaceAfter=30
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontName='SFPro',
        fontSize=11,
        leading=14
    )
    
    story = []
    
    # Заголовок
    story.append(Paragraph("ЗАЯВКА", title_style))
    story.append(Spacer(1, 20))
    
    # Информация о лоте
    lot_number = case_info.get('lastLegalCasenNumber', {}).get('value', 'N/A')
    debtor_name = case_info.get('debtorName', {}).get('value', 'N/A')
    
    story.append(Paragraph(f"<b>Лот №:</b> {lot_number}", normal_style))
    story.append(Paragraph(f"<b>Должник:</b> {debtor_name}", normal_style))
    story.append(Paragraph(f"<b>Управляющий:</b> {trustee_name}", normal_style))
    story.append(Spacer(1, 20))
    
    # Информация о заявителе
    story.append(Paragraph("<b>ИНФОРМАЦИЯ О ЗАЯВИТЕЛЕ:</b>", normal_style))
    story.append(Paragraph(f"ФИО: Хисматова Эльвира Василовна", normal_style))
    story.append(Paragraph(f"Дата рождения: {APPLICANT_BIRTH or 'N/A'}", normal_style))
    story.append(Paragraph(f"ИНН: {APPLICANT_INN or 'N/A'}", normal_style))
    story.append(Paragraph(f"ОГРНИП: {APPLICANT_OGRNIP or 'N/A'}", normal_style))
    story.append(Paragraph(f"Адрес: {APPLICANT_RES_ADDRESS or 'N/A'}", normal_style))
    story.append(Paragraph(f"Телефон: {APPLICANT_PHONE or 'N/A'}", normal_style))
    story.append(Paragraph(f"Email: {APPLICANT_EMAIL or 'N/A'}", normal_style))
    story.append(Spacer(1, 20))
    
    # Подпись
    story.append(Paragraph("___________________ / Хисматова Э.В.", normal_style))
    
    doc.build(story)
    return "Заявка.pdf"

# Функция для отправки email
def send_email(subject, attachment_path):
    if not all([EMAIL, EMAIL_PASSWORD, EMAIL_TO]):
        print("Email не настроен")
        return False
    
    msg = MIMEMultipart()
    msg['From'] = EMAIL_FROM or EMAIL
    msg['To'] = EMAIL_TO
    msg['Subject'] = Header(subject, 'utf-8')
    
    body = f"Заявка на участие в торгах.\n\nДата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    
    try:
        with open(attachment_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{os.path.basename(attachment_path)}"'
            )
            msg.attach(part)
    except Exception as e:
        print(f"Ошибка прикрепления файла: {e}")
        return False
    
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM or EMAIL, EMAIL_TO, msg.as_string())
        server.quit()
        print("✓ Email отправлен")
        return True
    except Exception as e:
        print(f"✗ Ошибка отправки email: {e}")
        return False

# Функция для обработки нового лота
async def process_new_lot(session, trustee_name, case_info, seen_cases):
    try:
        guid = case_info.get('guid', {}).get('value') or case_info.get('guid')
        if not guid:
            print("⚠ Нет GUID для лота")
            return
        
        if guid in seen_cases:
            return
        
        seen_cases.append(guid)
        
        # Получаем детали через API если нужно
        if 'lastLegalCasenNumber' not in case_info:
            details = await get_case_details_async(session, guid)
            if details and 'rez' in details:
                case_info = details['rez'][0]
        
        lot_number = case_info.get('lastLegalCasenNumber', {}).get('value', 'N/A')
        message = f"Новый лот от {trustee_name}: {lot_number}"
        print(f"🎯 {message}")
        
        # Отправляем уведомления
        await send_to_telegram(message)
        
        # Генерируем и отправляем PDF
        pdf_path = generate_pdf(trustee_name, case_info)
        subject = f"Заявка на {lot_number}"
        send_email(subject, pdf_path)
        
        # Удаляем временный файл
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            
    except Exception as e:
        print(f"Ошибка обработки лота: {e}")

async def run_http_server():
    app = web.Application()
    app.router.add_get('/health', handle_health)
    app.router.add_get('/status', handle_status)
    app.router.add_get('/', handle_health)  # Корневой путь тоже отдаём статус
    
    port = int(os.environ.get('PORT', 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✓ HTTP сервер запущен на порту {port} для Render health checks")
    return runner

# Основной цикл с использованием парсера
async def main(test_mode=False):
    print("=== BankrotParser v1.1 ===")
    print("=== Запуск с использованием парсера fedresurs.ru ===")
    
    # Запускаем HTTP сервер для Render
    http_runner = await run_http_server()
    
    if not PARSER_AVAILABLE:
        print("✗ Парсер недоступен. Установите зависимости: pip install selenium webdriver-manager")
        # Держим сервер запущенным даже без парсера, чтобы Render не падал
        while True:
            await asyncio.sleep(10)
        return
    
    print(f"Дата фильтра: не ранее {MIN_DATE.strftime('%d.%m.%Y')}")
    print(f"Управляющие: {len(TRUSTEE_NAMES)}")
    
    seen_cases = load_seen_cases()
    
    # Обработка сигналов завершения
    loop = asyncio.get_running_loop()
    stop_signal = asyncio.Event()
    
    def signal_handler():
        print("\n⚠️ Получен сигнал завершения, останавливаемся...")
        stop_signal.set()
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    async with aiohttp.ClientSession() as session:
        iterations = 0
        
        while not stop_signal.is_set():
            print(f"\n--- Итерация {iterations + 1} ---")
            
            # Получаем торги через парсер
            try:
                trades = get_all_trades()
                print(f"Найдено {len(trades)} торгов")
                
                for trade in trades:
                    await process_new_lot(session, trade['trustee_name'], trade, seen_cases)
                    
            except Exception as e:
                print(f"Ошибка парсера: {e}")
            
            save_seen_cases(seen_cases)
            
            iterations += 1
            if test_mode and iterations >= 2:
                break
            
            # Проверка с возможностью досрочного выхода
            for _ in range(300):  # 300 секунд с проверкой stop_signal
                if stop_signal.is_set():
                    break
                await asyncio.sleep(1)
    
    # Очистка перед выходом
    await http_runner.cleanup()
    print("✅ Сервис остановлен")

async def handle_health(request):
    return web.Response(text="BankrotParser is running")

async def handle_status(request):
    return web.json_response({
        "status": "running",
        "service": "BankrotParser",
        "parser_available": PARSER_AVAILABLE
    })


# Точка входа
if __name__ == '__main__':
    import sys
    
    test_mode = '--test' in sys.argv
    asyncio.run(main(test_mode=test_mode))
