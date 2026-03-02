#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت تيليجرام لتوليد وفحص أسماء المستخدمين المميزة
Telegram Premium Username Generator & Checker Bot
"""

import asyncio
import logging
import re
import json
import sqlite3
import aiohttp
import random
import string
import os
import sys
import time
import itertools
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from collections import defaultdict
from enum import Enum
import hashlib

# مكتبات التيليجرام
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, CommandHandler, MessageHandler, CallbackQueryHandler,
        ConversationHandler, filters, ContextTypes
    )
    from telegram.constants import ParseMode
except ImportError:
    print("الرجاء تثبيت مكتبة python-telegram-bot")
    sys.exit(1)

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== الإعدادات ====================

class Config:
    """فئة الإعدادات الرئيسية"""
    
    # توكن البوت
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "8389696171:AAHQJMDDibsJiIb3TftSQ_RmvmM3DyXGdMo")
    
    # معرف المطور الأساسي
    OWNER_ID = 6918240643
    
    # ملف قاعدة البيانات
    DATABASE_FILE = "username_generator.db"
    
    # إعدادات الفحص
    REQUEST_TIMEOUT = 10
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    MAX_CONCURRENT_CHECKS = 20  # عدد الفحوصات المتزامنة
    
    # الحدود اليومية
    FREE_GENERATE_LIMIT = 200
    PREMIUM_GENERATE_LIMIT = 10000
    ADMIN_GENERATE_LIMIT = 10000000

config = Config()

# حالات المحادثة
(MAIN_MENU, ADD_PATTERN, GENERATE_BY_PATTERN, BATCH_GENERATE,
 ADMIN_PANEL, PATTERN_SETTINGS, STATS_VIEW, BROADCAST,
 BAN_USER, PREMIUM_SETTINGS, VIEW_RESULTS) = range(11)

# ==================== قاعدة البيانات ====================

class Database:
    """فئة التعامل مع قاعدة البيانات"""
    
    def __init__(self, db_file):
        self.db_file = db_file
        self.init_db()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # جدول المستخدمين
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_admin INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    is_premium INTEGER DEFAULT 0,
                    premium_until TEXT,
                    joined_date TEXT,
                    last_activity TEXT,
                    total_generated INTEGER DEFAULT 0,
                    total_found INTEGER DEFAULT 0
                )
            ''')
            
            # جدول الإدمن
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    added_by INTEGER,
                    added_date TEXT,
                    level INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # جدول الأنماط المحفوظة
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    pattern TEXT NOT NULL,
                    description TEXT,
                    created_date TEXT,
                    is_public INTEGER DEFAULT 0,
                    usage_count INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # جدول النتائج (الأسماء المتاحة)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS available_usernames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    found_by INTEGER,
                    found_date TEXT,
                    pattern_used TEXT,
                    is_claimed INTEGER DEFAULT 0,
                    claimed_by INTEGER,
                    claimed_date TEXT,
                    FOREIGN KEY (found_by) REFERENCES users(user_id)
                )
            ''')
            
            # جدول عمليات التوليد
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS generation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    pattern TEXT,
                    count_generated INTEGER,
                    count_found INTEGER,
                    start_time TEXT,
                    end_time TEXT,
                    status TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # إضافة المطور كإدمن رئيسي
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, is_admin, joined_date)
                VALUES (?, 1, ?)
            ''', (config.OWNER_ID, datetime.now().isoformat()))
            
            cursor.execute('''
                INSERT OR IGNORE INTO admins (user_id, added_by, level)
                VALUES (?, ?, 999)
            ''', (config.OWNER_ID, config.OWNER_ID))
            
            conn.commit()
    
    def add_user(self, user_id, username, first_name, last_name):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO users 
                (user_id, username, first_name, last_name, joined_date, last_activity)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name, 
                  datetime.now().isoformat(), datetime.now().isoformat()))
            conn.commit()
    
    def update_activity(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET last_activity = ? WHERE user_id = ?
            ''', (datetime.now().isoformat(), user_id))
            conn.commit()
    
    def is_admin(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM admins WHERE user_id = ?', (user_id,))
            return cursor.fetchone() is not None
    
    def get_admin_level(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT level FROM admins WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 0
    
    def add_admin(self, user_id, added_by, level=1):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
            cursor.execute('''
                INSERT OR REPLACE INTO admins (user_id, added_by, added_date, level)
                VALUES (?, ?, ?, ?)
            ''', (user_id, added_by, datetime.now().isoformat(), level))
            cursor.execute('UPDATE users SET is_admin = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            return True
    
    def remove_admin(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
            cursor.execute('UPDATE users SET is_admin = 0 WHERE user_id = ?', (user_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def get_all_admins(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT a.*, u.username, u.first_name, u.last_name 
                FROM admins a
                JOIN users u ON a.user_id = u.user_id
                ORDER BY a.level DESC, a.added_date
            ''')
            return cursor.fetchall()
    
    def save_pattern(self, user_id, pattern, description="", is_public=0):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO patterns (user_id, pattern, description, created_date, is_public)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, pattern, description, datetime.now().isoformat(), is_public))
            conn.commit()
            return cursor.lastrowid
    
    def get_user_patterns(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM patterns 
                WHERE user_id = ? OR is_public = 1
                ORDER BY created_date DESC
            ''', (user_id,))
            return cursor.fetchall()
    
    def save_available_username(self, username, found_by, pattern_used):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO available_usernames 
                    (username, found_by, found_date, pattern_used)
                    VALUES (?, ?, ?, ?)
                ''', (username, found_by, datetime.now().isoformat(), pattern_used))
                
                # تحديث إحصائيات المستخدم
                cursor.execute('''
                    UPDATE users SET total_found = total_found + 1
                    WHERE user_id = ?
                ''', (found_by,))
                
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
    
    def log_generation(self, user_id, pattern, count_generated, count_found, status="completed"):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO generation_logs 
                (user_id, pattern, count_generated, count_found, start_time, end_time, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, pattern, count_generated, count_found, 
                  datetime.now().isoformat(), datetime.now().isoformat(), status))
            
            # تحديث إجمالي ما تم توليده
            cursor.execute('''
                UPDATE users SET total_generated = total_generated + ?
                WHERE user_id = ?
            ''', (count_generated, user_id))
            
            conn.commit()
    
    def get_user_stats(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT total_generated, total_found, is_premium, premium_until
                FROM users WHERE user_id = ?
            ''', (user_id,))
            return cursor.fetchone()
    
    def is_banned(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result is not None and result[0] == 1

    def ban_user(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    def unban_user(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    def set_premium(self, user_id, days=30):
        until = (datetime.now() + timedelta(days=days)).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
            cursor.execute(
                'UPDATE users SET is_premium = 1, premium_until = ? WHERE user_id = ?',
                (until, user_id)
            )
            conn.commit()
            return True

    def remove_premium(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE users SET is_premium = 0, premium_until = NULL WHERE user_id = ?',
                (user_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_premium_users(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT user_id, username, first_name, premium_until FROM users WHERE is_premium = 1'
            )
            return cursor.fetchall()

    def get_global_stats(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # إحصائيات عامة
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM available_usernames')
            total_found = cursor.fetchone()[0]
            
            cursor.execute('SELECT SUM(total_generated) FROM users')
            total_generated = cursor.fetchone()[0] or 0
            
            cursor.execute('SELECT COUNT(*) FROM admins')
            total_admins = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_premium = 1')
            total_premium = cursor.fetchone()[0]
            
            # آخر 10 أسماء مميزة تم العثور عليها
            cursor.execute('''
                SELECT * FROM available_usernames 
                ORDER BY found_date DESC LIMIT 10
            ''')
            recent = cursor.fetchall()
            
            return {
                'total_users': total_users,
                'total_found': total_found,
                'total_generated': total_generated,
                'total_admins': total_admins,
                'total_premium': total_premium,
                'recent_finds': recent
            }

# إنشاء كائن قاعدة البيانات
db = Database(config.DATABASE_FILE)

# ==================== مولد الأسماء المميزة ====================

class PremiumUsernameGenerator:
    """مولد أسماء المستخدمين المميزة"""
    
    def __init__(self):
        self.letters = string.ascii_lowercase
        self.digits = string.digits
        self.vowels = 'aeiou'
        self.consonants = 'bcdfghjklmnpqrstvwxyz'
        
        # كلمات شائعة للأسماء المميزة
        self.common_words = [
            'king', 'queen', 'prince', 'princess', 'lord', 'master',
            'pro', 'max', 'super', 'ultra', 'mega', 'hyper', 'alpha',
            'beta', 'gamma', 'delta', 'omega', 'star', 'moon', 'sun',
            'sky', 'fire', 'ice', 'wind', 'thunder', 'shadow', 'light',
            'dark', 'night', 'day', 'time', 'space', 'world', 'game',
            'play', 'win', 'lucky', 'gold', 'silver', 'diamond', 'ruby',
            'emerald', 'sapphire', 'crystal', 'storm', 'blade', 'sword',
            'shield', 'arrow', 'spear', 'wolf', 'lion', 'tiger', 'eagle',
            'hawk', 'falcon', 'dragon', 'phoenix', 'raven', 'crow'
        ]
        
        # أحرف مميزة للأنماط
        self.premium_chars = 'aeiouyAEIOUYbcdfghjklmnpqrstvwxzBCDFGHJKLMNPQRSTVWXZ'
    
    def generate_by_pattern(self, pattern: str, count: int = 10) -> List[str]:
        """توليد أسماء حسب نمط محدد"""
        usernames = []
        pattern = pattern.lower()
        
        # تحليل النمط
        if pattern == 'random':
            # أسماء عشوائية قصيرة
            for _ in range(count):
                length = random.randint(4, 6)
                name = ''.join(random.choices(self.letters, k=length))
                usernames.append(name)
        
        elif pattern == 'premium':
            # أسماء مميزة (كلمة + أرقام قليلة)
            for _ in range(count):
                word = random.choice(self.common_words)
                suffix = ''.join(random.choices(self.digits, k=random.randint(1, 2)))
                usernames.append(f"{word}{suffix}")
        
        elif pattern == 'short':
            # أسماء قصيرة جداً (3-4 أحرف)
            for _ in range(count):
                length = random.randint(3, 4)
                name = ''.join(random.choices(self.letters, k=length))
                usernames.append(name)
        
        elif '_' in pattern:
            # أنماط مع underscores مثل MM_MM
            parts = pattern.split('_')
            for _ in range(count):
                generated = []
                for part in parts:
                    if part.upper() == 'M':
                        # حرف عشوائي
                        generated.append(random.choice(self.letters))
                    elif part.upper() == 'C':
                        # حرف ساكن
                        generated.append(random.choice(self.consonants))
                    elif part.upper() == 'V':
                        # حرف علة
                        generated.append(random.choice(self.vowels))
                    elif part.upper() == 'D':
                        # رقم
                        generated.append(random.choice(self.digits))
                    else:
                        # نص ثابت
                        generated.append(part)
                usernames.append('_'.join(generated))
        
        elif pattern == 'MMM_MM':
            # نمط محدد: 3 أحرف + underscore + 2 أحرف
            for _ in range(count):
                part1 = ''.join(random.choices(self.letters, k=3))
                part2 = ''.join(random.choices(self.letters, k=2))
                usernames.append(f"{part1}_{part2}")
        
        elif pattern == 'MMORS':
            # نمط محدد
            for _ in range(count):
                base = ''.join(random.choices(self.letters, k=4))
                usernames.append(f"{base}rs")
        
        elif pattern == 'words':
            # كلمات مع أرقام
            for _ in range(count):
                word = random.choice(self.common_words)
                if random.choice([True, False]):
                    num = ''.join(random.choices(self.digits, k=random.randint(1, 3)))
                    usernames.append(f"{word}{num}")
                else:
                    usernames.append(word)
        
        elif pattern == 'leet':
            # أسماء باللغة العسكرية (1337)
            leet_map = {'a': '4', 'e': '3', 'i': '1', 'o': '0', 's': '5', 't': '7'}
            for _ in range(count):
                word = random.choice(self.common_words)
                leet_word = ''.join(leet_map.get(c, c) for c in word)
                usernames.append(leet_word)
        
        elif pattern == 'alternating':
            # أحرف متناوبة (كبير/صغير)
            for _ in range(count):
                length = random.randint(5, 7)
                name = []
                for i in range(length):
                    c = random.choice(self.letters)
                    if i % 2 == 0:
                        name.append(c.upper())
                    else:
                        name.append(c)
                usernames.append(''.join(name))
        
        elif pattern == 'date':
            # أسماء بتواريخ
            for _ in range(count):
                year = random.randint(90, 99)
                month = random.randint(1, 12)
                day = random.randint(1, 28)
                usernames.append(f"{random.choice(self.common_words)}{year}{month:02d}{day:02d}")
        
        elif pattern == 'double':
            # أسماء مكررة
            for _ in range(count):
                base = ''.join(random.choices(self.letters, k=2))
                usernames.append(f"{base}{base}")
        
        elif pattern == 'combined':
            # أسماء مركبة
            for _ in range(count):
                word1 = random.choice(self.common_words)
                word2 = random.choice(self.common_words)
                if word1 != word2:
                    usernames.append(f"{word1}{word2}")
        
        else:
            # أي نمط مخصص (يتعامل مع M كحرف)
            if all(c.isalpha() for c in pattern):
                # نمط مثل MMMMM (كلها أحرف)
                length = len(pattern)
                for _ in range(count):
                    name = ''.join(random.choices(self.letters, k=length))
                    usernames.append(name)
        
        # إزالة التكرارات
        usernames = list(dict.fromkeys(usernames))
        
        # التأكد من العدد المطلوب
        while len(usernames) < count:
            extra = random.choice(self.common_words)
            if extra not in usernames:
                usernames.append(extra)
        
        return usernames[:count]
    
    def generate_premium_batch(self, pattern_type: str, count: int) -> List[str]:
        """توليد مجموعة من الأسماء المميزة"""
        patterns = {
            'short': ['short', 'MMM', 'MMMM', 'CVCV'],
            'medium': ['MM_MM', 'MMM_MM', 'word123', 'premium'],
            'long': ['MMMM_MMM', 'word_word', 'combined', 'date'],
            'vip': ['MMORS', 'MMM_M', 'CVCCVC', 'leet'],
            'all': ['random', 'premium', 'short', 'MM_MM', 'MMORS', 'words', 'double']
        }
        
        selected_patterns = patterns.get(pattern_type, ['random'])
        all_usernames = []
        
        # توزيع العدد على الأنماط المختلفة
        per_pattern = max(1, count // len(selected_patterns))
        
        for pattern in selected_patterns:
            generated = self.generate_by_pattern(pattern, per_pattern)
            all_usernames.extend(generated)
        
        # إذا كان العدد أقل، نضيف المزيد
        while len(all_usernames) < count:
            all_usernames.append(self.generate_by_pattern('short', 1)[0])
        
        return list(dict.fromkeys(all_usernames))[:count]

# ==================== فاحص الأسماء ====================

class UsernameChecker:
    """فئة فحص أسماء المستخدمين"""
    
    def __init__(self):
        self.session = None
        self.base_url = "https://t.me/"
        self.results_queue = asyncio.Queue()
        self.available_count = 0
        self.checked_count = 0
    
    async def get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self):
        if self.session:
            await self.session.close()
    
    async def check_single(self, username: str) -> Dict[str, Any]:
        """فحص اسم مستخدم واحد"""
        try:
            username = username.lower().strip()
            url = f"{self.base_url}{username}"
            
            session = await self.get_session()
            timeout = aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT)
            async with session.get(url, timeout=timeout) as response:
                if response.status == 404:
                    return {
                        'username': username,
                        'available': True,
                        'method': 'web',
                        'quality': self.assess_quality(username)
                    }
                elif response.status == 200:
                    html = await response.text()
                    if 'tgme_page' in html and ('If you have Telegram' in html or 'جاري التحويل' in html):
                        return {
                            'username': username,
                            'available': False,
                            'method': 'web',
                            'details': 'مستخدم'
                        }
                
                return {
                    'username': username,
                    'available': True,
                    'method': 'fallback',
                    'quality': self.assess_quality(username)
                }
                
        except Exception as e:
            return {
                'username': username,
                'available': False,
                'method': 'error',
                'details': str(e)
            }
    
    def assess_quality(self, username: str) -> Dict[str, Any]:
        """تقييم جودة اسم المستخدم"""
        score = 0
        reasons = []
        
        # الأسماء القصيرة أفضل
        length = len(username)
        if length <= 4:
            score += 10
            reasons.append("قصير جداً")
        elif length <= 6:
            score += 7
            reasons.append("قصير")
        elif length <= 8:
            score += 4
            reasons.append("متوسط")
        
        # الأسماء بدون أرقام أفضل
        if not any(c.isdigit() for c in username):
            score += 5
            reasons.append("بدون أرقام")
        
        # الأسماء بدون underscores أفضل
        if '_' not in username:
            score += 3
            reasons.append("بدون شرطة سفلية")
        
        # كلمات إنجليزية شائعة
        common_words = ['king', 'queen', 'pro', 'max', 'super', 'mega', 'ultra']
        if any(word in username for word in common_words):
            score += 8
            reasons.append("كلمة شائعة")
        
        # تكرار الأحرف
        if len(set(username)) / len(username) > 0.7:
            score += 4
            reasons.append("أحرف متنوعة")
        
        # تقييم النهائي
        if score >= 20:
            quality = "ممتاز"
        elif score >= 15:
            quality = "جيد جداً"
        elif score >= 10:
            quality = "جيد"
        elif score >= 5:
            quality = "متوسط"
        else:
            quality = "عادي"
        
        return {
            'score': score,
            'quality': quality,
            'reasons': reasons
        }
    
    async def check_batch(self, usernames: List[str], progress_callback=None) -> List[Dict]:
        """فحص مجموعة أسماء"""
        results = []
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_CHECKS)
        
        async def check_with_limit(username):
            async with semaphore:
                result = await self.check_single(username)
                self.checked_count += 1
                if result['available']:
                    self.available_count += 1
                    await self.results_queue.put(result)
                
                if progress_callback:
                    await progress_callback(self.checked_count, len(usernames))
                
                return result
        
        tasks = [check_with_limit(username) for username in usernames]
        results = await asyncio.gather(*tasks)
        
        return results
    
    async def get_results_summary(self) -> Dict[str, Any]:
        """الحصول على ملخص النتائج"""
        available = []
        while not self.results_queue.empty():
            available.append(await self.results_queue.get())
        
        # ترتيب حسب الجودة
        available.sort(key=lambda x: x.get('quality', {}).get('score', 0) if isinstance(x.get('quality'), dict) else 0, reverse=True)
        
        return {
            'total_checked': self.checked_count,
            'total_available': len(available),
            'available_names': available,
            'percentage': (len(available) / self.checked_count * 100) if self.checked_count > 0 else 0
        }

# ==================== واجهة المستخدم ====================

def get_main_keyboard(is_admin: bool = False):
    """لوحة المفاتيح الرئيسية"""
    keyboard = [
        [InlineKeyboardButton("🎲 توليد وفحص عشوائي", callback_data="generate_random")],
        [InlineKeyboardButton("🔤 توليد بنمط محدد", callback_data="generate_pattern")],
        [InlineKeyboardButton("📋 أنماط متعددة", callback_data="batch_patterns")],
        [InlineKeyboardButton("⭐ أفضل الأنماط", callback_data="premium_patterns")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="my_stats")],
        [InlineKeyboardButton("🏆 آخر الأسماء المتاحة", callback_data="recent_finds")]
    ]
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم الإدمن", callback_data="admin_panel")])
    
    keyboard.append([InlineKeyboardButton("❓ مساعدة", callback_data="help")])
    
    return InlineKeyboardMarkup(keyboard)

def get_pattern_keyboard():
    """لوحة أنماط التوليد"""
    keyboard = [
        [InlineKeyboardButton("🎯 أسماء قصيرة (3-4 أحرف)", callback_data="pattern_short")],
        [InlineKeyboardButton("🔤 نمط MM_MM", callback_data="pattern_mm_mm")],
        [InlineKeyboardButton("📝 نمط MMM_MM", callback_data="pattern_mmm_mm")],
        [InlineKeyboardButton("💎 نمط MMORS", callback_data="pattern_mmors")],
        [InlineKeyboardButton("✨ نمط MMM_M", callback_data="pattern_mmm_m")],
        [InlineKeyboardButton("🌟 كلمات شائعة + أرقام", callback_data="pattern_words")],
        [InlineKeyboardButton("🎮 أسماء الألعاب", callback_data="pattern_gaming")],
        [InlineKeyboardButton("📅 أسماء بتواريخ", callback_data="pattern_dates")],
        [InlineKeyboardButton("🔄 توليد الكل", callback_data="pattern_all")],
        [InlineKeyboardButton("✏️ نمط مخصص", callback_data="custom_pattern")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_batch_keyboard():
    """لوحة كميات التوليد"""
    keyboard = [
        [InlineKeyboardButton("🔟 10 أسماء", callback_data="batch_10")],
        [InlineKeyboardButton("5️⃣0️⃣ 50 اسم", callback_data="batch_50")],
        [InlineKeyboardButton("1️⃣0️⃣0️⃣ 100 اسم", callback_data="batch_100")],
        [InlineKeyboardButton("5️⃣0️⃣0️⃣ 500 اسم", callback_data="batch_500")],
        [InlineKeyboardButton("1️⃣0️⃣0️⃣0️⃣ 1000 اسم", callback_data="batch_1000")],
        [InlineKeyboardButton("🔢 عدد مخصص", callback_data="custom_count")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_patterns")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    """لوحة تحكم الإدمن"""
    keyboard = [
        [InlineKeyboardButton("👥 إدارة الإدمن", callback_data="admin_manage")],
        [InlineKeyboardButton("📊 إحصائيات عامة", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 إذاعة", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🚫 حظر/إلغاء حظر", callback_data="admin_ban")],
        [InlineKeyboardButton("⭐ إدارة المميزين", callback_data="admin_premium")],
        [InlineKeyboardButton("📁 الأنماط المحفوظة", callback_data="admin_patterns")],
        [InlineKeyboardButton("⚙️ إعدادات البوت", callback_data="admin_settings")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== معالجات الأوامر الأساسية ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /start"""
    user = update.effective_user
    
    # إضافة المستخدم
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    db.update_activity(user.id)
    
    # رسالة الترحيب
    welcome_text = f"""
🎉 **أهلاً بك في بوت توليد وفحص الأسماء المميزة** {user.first_name}!

🚀 **مميزات البوت:**
• توليد آلاف الأسماء العشوائية المميزة
• فحص تلقائي للأسماء المتاحة
• أنماط متعددة: MM_MM, MMM_MM, MMORS, MMM_M
• تقييم جودة الأسماء المتاحة
• حفظ النتائج وعرضها

🔹 **اختر من القائمة للبدء**
    """
    
    is_admin = db.is_admin(user.id)
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard(is_admin),
        parse_mode=ParseMode.MARKDOWN
    )

# ==================== معالجات التوليد والفحص ====================

async def generate_random_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """توليد وفحص أسماء عشوائية"""
    query = update.callback_query
    await query.answer()
    
    # عرض اختيار الكمية
    await query.edit_message_text(
        "اختر عدد الأسماء المراد توليدها وفحصها:",
        reply_markup=get_batch_keyboard()
    )
    
    # تخزين نوع العملية
    context.user_data['generation_type'] = 'random'

async def generate_pattern_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """توليد بنمط محدد"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🎯 **اختر نمط التوليد:**\n\n"
        "• MM_MM - حرفين + شرطة + حرفين\n"
        "• MMM_MM - 3 أحرف + شرطة + حرفين\n"
        "• MMORS - نمط خاص\n"
        "• MMM_M - 3 أحرف + شرطة + حرف\n"
        "• كلمات شائعة - king, pro, max...\n"
        "• أسماء قصيرة - 3-4 أحرف\n"
        "• نمط مخصص - أدخل النمط الذي تريده",
        reply_markup=get_pattern_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def process_pattern_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار النمط"""
    query = update.callback_query
    await query.answer()
    
    pattern_map = {
        'pattern_short': 'short',
        'pattern_mm_mm': 'MM_MM',
        'pattern_mmm_mm': 'MMM_MM',
        'pattern_mmors': 'MMORS',
        'pattern_mmm_m': 'MMM_M',
        'pattern_words': 'words',
        'pattern_gaming': 'premium',
        'pattern_dates': 'date',
        'pattern_all': 'all'
    }
    
    selected = query.data
    if selected in pattern_map:
        context.user_data['selected_pattern'] = pattern_map[selected]
        await query.edit_message_text(
            f"النمط المختار: {pattern_map[selected]}\n\nاختر عدد الأسماء:",
            reply_markup=get_batch_keyboard()
        )
    elif selected == 'custom_pattern':
        context.user_data['awaiting_pattern'] = True
        await query.edit_message_text(
            "✏️ أرسل النمط المخصص الذي تريده:\n\n"
            "مثال: MM_MM أو MMM_MM أو أي نمط آخر\n"
            "(M = حرف، D = رقم)"
        )

async def process_batch_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار الكمية والبدء بالتوليد"""
    query = update.callback_query
    await query.answer()
    
    batch_map = {
        'batch_10': 10,
        'batch_50': 50,
        'batch_100': 100,
        'batch_500': 500,
        'batch_1000': 1000
    }
    
    if query.data in batch_map:
        count = batch_map[query.data]
        await start_generation(update, context, count)
    elif query.data == 'custom_count':
        context.user_data['awaiting_custom_count'] = True
        await query.edit_message_text("أرسل العدد المطلوب (1-10000):")

async def start_generation(update: Update, context: ContextTypes.DEFAULT_TYPE, count: int):
    """بدء عملية التوليد والفحص"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # التحقق من الحدود
    user_stats = db.get_user_stats(user_id)
    is_premium = user_stats and user_stats['is_premium'] if user_stats else False
    is_admin = db.is_admin(user_id)
    
    # تحديد الحد الأقصى حسب نوع المستخدم
    if is_admin:
        max_allowed = config.ADMIN_GENERATE_LIMIT
    elif is_premium:
        max_allowed = config.PREMIUM_GENERATE_LIMIT
    else:
        max_allowed = config.FREE_GENERATE_LIMIT
    
    if count > max_allowed:
        await query.edit_message_text(
            f"⚠️ لا يمكنك توليد أكثر من {max_allowed} اسم في المرة الواحدة.\n"
            f"اشتراك Premium يتيح لك توليد {config.PREMIUM_GENERATE_LIMIT} اسم."
        )
        return
    
    # إرسال رسالة البدء
    progress_msg = await query.edit_message_text(
        f"🔄 جاري توليد وفحص {count} اسم...\n"
        f"⏳ هذا قد يستغرق بعض الوقت"
    )
    
    # توليد الأسماء
    generator = PremiumUsernameGenerator()
    pattern = context.user_data.get('selected_pattern', 'all')
    usernames = generator.generate_premium_batch(pattern, count)
    
    # فحص الأسماء
    checker = UsernameChecker()
    
    # دالة تحديث التقدم
    async def update_progress(checked, total):
        if checked % 50 == 0 or checked == total:
            try:
                await progress_msg.edit_text(
                    f"🔄 جاري الفحص...\n"
                    f"✅ تم فحص: {checked}/{total}\n"
                    f"💚 تم العثور: {checker.available_count}"
                )
            except:
                pass
    
    # بدء الفحص
    results = await checker.check_batch(usernames, update_progress)
    summary = await checker.get_results_summary()
    
    # حفظ النتائج في قاعدة البيانات
    for available in summary['available_names']:
        db.save_available_username(
            available['username'],
            user_id,
            pattern
        )
    
    # تسجيل العملية
    db.log_generation(
        user_id,
        pattern,
        count,
        summary['total_available']
    )
    
    # تجهيز رسالة النتائج
    result_text = f"""
✅ **اكتمل الفحص!**

📊 **النتائج:**
• تم فحص: {summary['total_checked']} اسم
• أسماء متاحة: {summary['total_available']}
• نسبة المتاح: {summary['percentage']:.1f}%

🏆 **أفضل 5 أسماء متاحة:**
"""
    
    for i, name in enumerate(summary['available_names'][:5], 1):
        quality = name.get('quality', {}).get('quality', 'غير معروف') if isinstance(name.get('quality'), dict) else 'غير معروف'
        result_text += f"{i}. @{name['username']} - {quality}\n"
    
    # أزرار النتائج
    keyboard = [
        [InlineKeyboardButton("📥 عرض كل النتائج", callback_data="view_all_results")],
        [InlineKeyboardButton("🔄 توليد مرة أخرى", callback_data="generate_random")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="back_main")]
    ]
    
    await progress_msg.edit_text(
        result_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    
    await checker.close()

# ==================== معالجات الإدمن ====================

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لوحة تحكم الإدمن"""
    query = update.callback_query
    await query.answer()
    
    if not db.is_admin(update.effective_user.id):
        await query.edit_message_text("⛔ هذه الخاصية للمشرفين فقط")
        return
    
    await query.edit_message_text(
        "⚙️ **لوحة تحكم الإدمن**\n\n"
        "اختر ما تريد:",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_manage_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة الإدمن"""
    query = update.callback_query
    await query.answer()
    
    admins = db.get_all_admins()
    
    admin_list = "👥 **قائمة الإدمن:**\n\n"
    for admin in admins:
        level = "👑 مالك" if admin['level'] >= 999 else f"⚜️ مستوى {admin['level']}"
        name = admin['first_name'] or admin['username'] or str(admin['user_id'])
        admin_list += f"• {name} - {level}\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ إضافة إدمن", callback_data="admin_add")],
        [InlineKeyboardButton("➖ إزالة إدمن", callback_data="admin_remove")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ]
    
    await query.edit_message_text(
        admin_list,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إحصائيات عامة"""
    query = update.callback_query
    await query.answer()
    
    stats = db.get_global_stats()
    
    stats_text = f"""
📊 **إحصائيات البوت العامة**

👥 **المستخدمين:**
• إجمالي المستخدمين: {stats['total_users']}
• المشرفين: {stats['total_admins']}
• المميزين: {stats['total_premium']}

🔍 **الفحوصات:**
• إجمالي الأسماء المولدة: {stats['total_generated']}
• الأسماء المتاحة: {stats['total_found']}
• نسبة المتاح: {(stats['total_found']/stats['total_generated']*100) if stats['total_generated'] > 0 else 0:.1f}%

🏆 **آخر الأسماء المتاحة:**
"""
    
    for i, name in enumerate(stats['recent_finds'][:5], 1):
        stats_text += f"{i}. @{name['username']}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    
    await query.edit_message_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إذاعة رسالة للمستخدمين"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['awaiting_broadcast'] = True
    
    await query.edit_message_text(
        "📢 أرسل الرسالة التي تريد إذاعتها لجميع المستخدمين:"
    )

async def admin_ban_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حظر مستخدم"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['awaiting_ban_user'] = True
    
    await query.edit_message_text(
        "🚫 أرسل معرف المستخدم (User ID) الذي تريد حظره:"
    )

async def admin_premium_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة المستخدمين المميزين"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("⭐ إضافة مميز", callback_data="premium_add")],
        [InlineKeyboardButton("⭐ إزالة مميز", callback_data="premium_remove")],
        [InlineKeyboardButton("📋 قائمة المميزين", callback_data="premium_list")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ]
    
    await query.edit_message_text(
        "⭐ **إدارة المستخدمين المميزين**\n\n"
        "اختر ما تريد:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

# ==================== معالجات عرض النتائج ====================

async def view_all_results_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض كل النتائج"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM available_usernames 
            WHERE found_by = ?
            ORDER BY found_date DESC LIMIT 50
        ''', (user_id,))
        results = cursor.fetchall()
    
    if not results:
        await query.edit_message_text(
            "لم يتم العثور على أي أسماء متاحة بعد.\n"
            "جرب توليد وفحص بعض الأسماء أولاً!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="back_main")
            ]])
        )
        return
    
    # تقسيم النتائج إلى صفحات
    page = context.user_data.get('results_page', 0)
    start = page * 10
    end = start + 10
    page_results = results[start:end]
    
    text = f"📥 **النتائج المحفوظة (صفحة {page + 1}/{(len(results)-1)//10 + 1})**\n\n"
    for r in page_results:
        quality = "⭐⭐⭐⭐⭐" if random.random() > 0.5 else "⭐⭐⭐⭐"  # يمكن تحسين هذا
        text += f"{quality} @{r['username']}\n"
    
    # أزرار التنقل بين الصفحات
    keyboard = []
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ السابق", callback_data="results_prev"))
    if end < len(results):
        nav_buttons.append(InlineKeyboardButton("التالي ▶️", callback_data="results_next"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="back_main")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

# ==================== معالجات النصوص ====================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج النصوص"""
    user_id = update.effective_user.id
    text = update.message.text
    
    db.update_activity(user_id)
    
    # التحقق من الحظر
    if db.is_banned(user_id):
        await update.message.reply_text("🚫 أنت محظور من استخدام البوت")
        return
    
    # معالجة النمط المخصص
    if context.user_data.get('awaiting_pattern'):
        context.user_data['selected_pattern'] = text
        context.user_data['awaiting_pattern'] = False
        
        await update.message.reply_text(
            f"النمط المخصص: {text}\n\nاختر عدد الأسماء:",
            reply_markup=get_batch_keyboard()
        )
        return
    
    # معالجة العدد المخصص
    if context.user_data.get('awaiting_custom_count'):
        try:
            count = int(text)
            if 1 <= count <= 10000:
                context.user_data['awaiting_custom_count'] = False
                # بدء التوليد
                await start_generation_from_message(update, context, count)
            else:
                await update.message.reply_text("الرجاء إدخال عدد بين 1 و 10000")
        except ValueError:
            await update.message.reply_text("الرجاء إدخال رقم صحيح")
        return
    
    # معالجة إذاعة الإدمن
    if context.user_data.get('awaiting_broadcast') and db.is_admin(user_id):
        context.user_data['awaiting_broadcast'] = False
        
        # إرسال تأكيد
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ تأكيد", callback_data="broadcast_confirm"),
                InlineKeyboardButton("❌ إلغاء", callback_data="broadcast_cancel")
            ]
        ])
        
        context.user_data['broadcast_message'] = text
        await update.message.reply_text(
            f"📢 رسالة الإذاعة:\n\n{text}\n\nهل أنت متأكد؟",
            reply_markup=confirm_keyboard
        )
        return
    
    # معالجة حظر المستخدم
    if context.user_data.get('awaiting_ban_user') and db.is_admin(user_id):
        try:
            target_id = int(text)
            if db.ban_user(target_id):
                await update.message.reply_text(f"✅ تم حظر المستخدم {target_id}")
            else:
                await update.message.reply_text("❌ المستخدم غير موجود")
        except ValueError:
            await update.message.reply_text("❌ معرف غير صالح")
        context.user_data['awaiting_ban_user'] = False
        return

    # معالجة إضافة إدمن
    if context.user_data.get('awaiting_add_admin') and db.is_admin(user_id):
        try:
            target_id = int(text)
            db.add_admin(target_id, user_id, level=1)
            await update.message.reply_text(f"✅ تم إضافة المستخدم {target_id} كإدمن")
        except ValueError:
            await update.message.reply_text("❌ معرف غير صالح")
        context.user_data['awaiting_add_admin'] = False
        return

    # معالجة إزالة إدمن
    if context.user_data.get('awaiting_remove_admin') and db.is_admin(user_id):
        try:
            target_id = int(text)
            if db.remove_admin(target_id):
                await update.message.reply_text(f"✅ تم إزالة المستخدم {target_id} من الإدمن")
            else:
                await update.message.reply_text("❌ المستخدم ليس إدمناً")
        except ValueError:
            await update.message.reply_text("❌ معرف غير صالح")
        context.user_data['awaiting_remove_admin'] = False
        return

    # معالجة إضافة مميز
    if context.user_data.get('awaiting_add_premium') and db.is_admin(user_id):
        try:
            target_id = int(text)
            db.set_premium(target_id, days=30)
            await update.message.reply_text(f"✅ تم تفعيل الاشتراك المميز للمستخدم {target_id}")
        except ValueError:
            await update.message.reply_text("❌ معرف غير صالح")
        context.user_data['awaiting_add_premium'] = False
        return

    # معالجة إزالة مميز
    if context.user_data.get('awaiting_remove_premium') and db.is_admin(user_id):
        try:
            target_id = int(text)
            if db.remove_premium(target_id):
                await update.message.reply_text(f"✅ تم إلغاء اشتراك المستخدم {target_id} المميز")
            else:
                await update.message.reply_text("❌ المستخدم غير موجود")
        except ValueError:
            await update.message.reply_text("❌ معرف غير صالح")
        context.user_data['awaiting_remove_premium'] = False
        return

    
    # إذا كان النص يبدو كاسم مستخدم
    if text.startswith('@') or re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', text):
        # فحص مباشر
        await update.message.reply_text(f"🔍 جاري فحص @{text.lstrip('@')}...")
        
        checker = UsernameChecker()
        result = await checker.check_single(text.lstrip('@'))
        await checker.close()
        
        if result['available']:
            quality = result['quality']['quality']
            await update.message.reply_text(
                f"✅ @{result['username']} متاح!\n"
                f"📊 الجودة: {quality}\n"
                f"⚡ سارع بتسجيله!"
            )
        else:
            await update.message.reply_text(
                f"❌ @{result['username']} غير متاح\n"
                f"السبب: {result.get('details', 'مستخدم بالفعل')}"
            )
    else:
        await update.message.reply_text(
            "❓ أرسل اسم مستخدم للفحص المباشر\n"
            "أو استخدم الأزرار للتوليد والفحص التلقائي"
        )

async def start_generation_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE, count: int):
    """بدء التوليد من رسالة"""
    user_id = update.effective_user.id
    
    # إرسال رسالة البدء
    progress_msg = await update.message.reply_text(
        f"🔄 جاري توليد وفحص {count} اسم...\n"
        f"⏳ هذا قد يستغرق بعض الوقت"
    )
    
    # توليد الأسماء
    generator = PremiumUsernameGenerator()
    pattern = context.user_data.get('selected_pattern', 'all')
    usernames = generator.generate_premium_batch(pattern, count)
    
    # فحص الأسماء
    checker = UsernameChecker()
    
    # دالة تحديث التقدم
    async def update_progress(checked, total):
        if checked % 50 == 0 or checked == total:
            try:
                await progress_msg.edit_text(
                    f"🔄 جاري الفحص...\n"
                    f"✅ تم فحص: {checked}/{total}\n"
                    f"💚 تم العثور: {checker.available_count}"
                )
            except:
                pass
    
    # بدء الفحص
    results = await checker.check_batch(usernames, update_progress)
    summary = await checker.get_results_summary()
    
    # حفظ النتائج
    for available in summary['available_names']:
        db.save_available_username(
            available['username'],
            user_id,
            pattern
        )
    
    # تسجيل العملية
    db.log_generation(
        user_id,
        pattern,
        count,
        summary['total_available']
    )
    
    # تجهيز النتائج
    result_text = f"""
✅ **اكتمل الفحص!**

📊 **النتائج:**
• تم فحص: {summary['total_checked']} اسم
• أسماء متاحة: {summary['total_available']}
• نسبة المتاح: {summary['percentage']:.1f}%

🏆 **أفضل 5 أسماء متاحة:**
"""
    
    for i, name in enumerate(summary['available_names'][:5], 1):
        quality = name.get('quality', {}).get('quality', 'غير معروف') if isinstance(name.get('quality'), dict) else 'غير معروف'
        result_text += f"{i}. @{name['username']} - {quality}\n"
    
    # أزرار النتائج
    keyboard = [
        [InlineKeyboardButton("📥 عرض كل النتائج", callback_data="view_all_results")],
        [InlineKeyboardButton("🔄 توليد مرة أخرى", callback_data="generate_random")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="back_main")]
    ]
    
    await progress_msg.edit_text(
        result_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    
    await checker.close()

async def help_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر المساعدة"""
    query = update.callback_query
    await query.answer()
    help_text = """
❓ **مساعدة البوت**

🎲 **التوليد العشوائي:** توليد أسماء عشوائية وفحصها
🔤 **توليد بنمط:** استخدام أنماط مثل MM_MM, MMM_MM
📋 **أنماط متعددة:** تجربة عدة أنماط في نفس الوقت

**الأنماط المتاحة:**
• MM_MM - حرفين + شرطة + حرفين
• MMM_MM - 3 أحرف + شرطة + حرفين
• MMORS - نمط خاص
• MMM_M - 3 أحرف + شرطة + حرف
• كلمات شائعة - king, pro, max
• أسماء قصيرة - 3-4 أحرف
• أسماء بأرقام - اسم + أرقام

**الأوامر:**
/start - بدء البوت
/help - عرض المساعدة
/stats - إحصائياتي
    """
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]
    await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)




# ==================== إعداد البوت ====================


async def admin_add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة إدمن جديد"""
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_add_admin'] = True
    await query.edit_message_text("➕ أرسل معرف المستخدم (User ID) لإضافته كإدمن:")

async def admin_remove_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إزالة إدمن"""
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_remove_admin'] = True
    await query.edit_message_text("➖ أرسل معرف المستخدم (User ID) لإزالته من الإدمن:")

async def premium_add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة مستخدم مميز"""
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_add_premium'] = True
    await query.edit_message_text("⭐ أرسل معرف المستخدم لإضافته كعضو مميز (مدة 30 يوم):")

async def premium_remove_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إزالة مستخدم مميز"""
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_remove_premium'] = True
    await query.edit_message_text("⭐ أرسل معرف المستخدم لإلغاء اشتراكه المميز:")

async def premium_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """قائمة المميزين"""
    query = update.callback_query
    await query.answer()
    users = db.get_premium_users()
    text = "⭐ **قائمة المستخدمين المميزين:**\n\n"
    if users:
        for u in users:
            name = u['first_name'] or u['username'] or str(u['user_id'])
            text += f"• {name} (حتى: {u['premium_until'][:10] if u['premium_until'] else 'غير محدد'})\n"
    else:
        text += "لا يوجد مستخدمون مميزون حالياً."
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_premium")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def admin_patterns_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الأنماط المحفوظة - لوحة الإدمن"""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await query.edit_message_text(
        "📁 **الأنماط المحفوظة**\n\nهذه الميزة قيد التطوير.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعدادات البوت"""
    query = update.callback_query
    await query.answer()
    text = f"""
⚙️ **إعدادات البوت الحالية**

🔢 حد المجاني: {config.FREE_GENERATE_LIMIT} اسم/مرة
⭐ حد المميز: {config.PREMIUM_GENERATE_LIMIT} اسم/مرة
👑 حد الإدمن: {config.ADMIN_GENERATE_LIMIT} اسم/مرة
🔄 فحوصات متزامنة: {config.MAX_CONCURRENT_CHECKS}
    """
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def batch_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج اختيار نوع الأنماط المتعددة"""
    query = update.callback_query
    await query.answer()
    type_map = {
        'batch_type_short': 'short',
        'batch_type_medium': 'medium',
        'batch_type_vip': 'vip',
        'batch_type_all': 'all'
    }
    selected = type_map.get(query.data, 'all')
    context.user_data['selected_pattern'] = selected
    await query.edit_message_text(
        f"النمط المختار: {selected}\n\nاختر عدد الأسماء:",
        reply_markup=get_batch_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر المساعدة"""
    help_text = """
❓ **مساعدة البوت**

🎲 **التوليد العشوائي:** توليد أسماء عشوائية وفحصها
🔤 **توليد بنمط:** استخدام أنماط مثل MM_MM, MMM_MM
📋 **أنماط متعددة:** تجربة عدة أنماط في نفس الوقت

**الأنماط المتاحة:**
• MM_MM - حرفين + شرطة + حرفين
• MMM_MM - 3 أحرف + شرطة + حرفين
• MMORS - نمط خاص
• MMM_M - 3 أحرف + شرطة + حرف
• كلمات شائعة - king, pro, max
• أسماء قصيرة - 3-4 أحرف
• أسماء بأرقام - اسم + أرقام

**الأوامر:**
/start - بدء البوت
/help - عرض المساعدة
/stats - إحصائياتي

استمتع بالبحث عن الأسماء المميزة! 🎯
    """
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


def main():
    """الدالة الرئيسية لتشغيل البوت"""
    
    # إنشاء التطبيق
    application = Application.builder().token(config.BOT_TOKEN).build()
    
    # إضافة معالجات الأوامر
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # معالجات الأزرار
    application.add_handler(CallbackQueryHandler(generate_random_handler, pattern="^generate_random$"))
    application.add_handler(CallbackQueryHandler(generate_pattern_handler, pattern="^generate_pattern$"))
    application.add_handler(CallbackQueryHandler(batch_patterns_handler, pattern="^batch_patterns$"))
    application.add_handler(CallbackQueryHandler(premium_patterns_handler, pattern="^premium_patterns$"))
    application.add_handler(CallbackQueryHandler(my_stats_handler, pattern="^my_stats$"))
    application.add_handler(CallbackQueryHandler(recent_finds_handler, pattern="^recent_finds$"))
    application.add_handler(CallbackQueryHandler(admin_panel_handler, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(admin_manage_handler, pattern="^admin_manage$"))
    application.add_handler(CallbackQueryHandler(admin_stats_handler, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(admin_broadcast_handler, pattern="^admin_broadcast$"))
    application.add_handler(CallbackQueryHandler(admin_ban_handler, pattern="^admin_ban$"))
    application.add_handler(CallbackQueryHandler(admin_premium_handler, pattern="^admin_premium$"))
    application.add_handler(CallbackQueryHandler(admin_add_handler, pattern="^admin_add$"))
    application.add_handler(CallbackQueryHandler(admin_remove_handler, pattern="^admin_remove$"))
    application.add_handler(CallbackQueryHandler(admin_patterns_handler, pattern="^admin_patterns$"))
    application.add_handler(CallbackQueryHandler(admin_settings_handler, pattern="^admin_settings$"))
    application.add_handler(CallbackQueryHandler(premium_add_handler, pattern="^premium_add$"))
    application.add_handler(CallbackQueryHandler(premium_remove_handler, pattern="^premium_remove$"))
    application.add_handler(CallbackQueryHandler(premium_list_handler, pattern="^premium_list$"))
    application.add_handler(CallbackQueryHandler(batch_type_handler, pattern="^batch_type_"))
    application.add_handler(CallbackQueryHandler(help_callback_handler, pattern="^help$"))
    application.add_handler(CallbackQueryHandler(back_main_handler, pattern="^back_main$"))
    application.add_handler(CallbackQueryHandler(back_patterns_handler, pattern="^back_patterns$"))
    
    # معالجات الأنماط
    application.add_handler(CallbackQueryHandler(process_pattern_selection, pattern="^pattern_"))
    application.add_handler(CallbackQueryHandler(process_pattern_selection, pattern="^custom_pattern$"))
    
    # معالجات الكميات
    application.add_handler(CallbackQueryHandler(process_batch_selection, pattern="^batch_(10|50|100|500|1000)$"))
    application.add_handler(CallbackQueryHandler(custom_count_handler, pattern="^custom_count$"))
    
    # معالجات النتائج
    application.add_handler(CallbackQueryHandler(view_all_results_handler, pattern="^view_all_results$"))
    application.add_handler(CallbackQueryHandler(results_navigation_handler, pattern="^results_(next|prev)$"))
    
    # معالجات الإذاعة
    application.add_handler(CallbackQueryHandler(broadcast_confirm_handler, pattern="^broadcast_confirm$"))
    application.add_handler(CallbackQueryHandler(broadcast_cancel_handler, pattern="^broadcast_cancel$"))
    
    # معالج النصوص
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # بدء البوت
    print("✅ البوت يعمل...")
    application.run_polling(drop_pending_updates=True)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر الإحصائيات"""
    user_id = update.effective_user.id
    stats = db.get_user_stats(user_id)
    
    if stats:
        text = f"""
📊 **إحصائياتك الشخصية**

🔢 إجمالي ما تم توليده: {stats['total_generated']}
✅ أسماء متاحة تم العثور عليها: {stats['total_found']}
📈 نسبة النجاح: {(stats['total_found']/stats['total_generated']*100) if stats['total_generated'] > 0 else 0:.1f}%

⭐ حالة الحساب: {'مميز' if stats['is_premium'] else 'عادي'}
        """
        
        if stats['premium_until']:
            text += f"\n📅 صلاحية المميز حتى: {stats['premium_until']}"
    else:
        text = "لا توجد إحصائيات بعد"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def batch_patterns_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأنماط المتعددة"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🎯 أنماط قصيرة", callback_data="batch_type_short")],
        [InlineKeyboardButton("📝 أنماط متوسطة", callback_data="batch_type_medium")],
        [InlineKeyboardButton("💎 أنماط VIP", callback_data="batch_type_vip")],
        [InlineKeyboardButton("🌐 كل الأنماط", callback_data="batch_type_all")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_patterns")]
    ]
    
    await query.edit_message_text(
        "📋 **الأنماط المتعددة**\n\n"
        "اختر نوع الأنماط التي تريد توليدها:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def premium_patterns_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أفضل الأنماط"""
    query = update.callback_query
    await query.answer()
    
    text = """
🏆 **أفضل الأنماط المقترحة:**

1. **MM_MM** - نمط كلاسيكي
2. **MMM_MM** - نمط متوازن
3. **MMORS** - نمط فريد
4. **CVCV** - حرف ساكن + متحرك
5. **word123** - كلمة + أرقام
6. **XX_XX** - أحرف مكررة
7. **date** - أسماء بتواريخ
8. **leet** - أسماء بالشيفرة

اختر نمطاً من القائمة الرئيسية للبدء!
    """
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_patterns")]]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def my_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج إحصائياتي"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    stats = db.get_user_stats(user_id)

    if stats:
        total_gen = stats['total_generated'] or 0
        total_found = stats['total_found'] or 0
        text = f"""
📊 **إحصائياتك الشخصية**

🔢 إجمالي ما تم توليده: {total_gen}
✅ أسماء متاحة تم العثور عليها: {total_found}
📈 نسبة النجاح: {(total_found/total_gen*100) if total_gen > 0 else 0:.1f}%

⭐ حالة الحساب: {'مميز' if stats['is_premium'] else 'عادي'}
        """
        if stats['premium_until']:
            text += f"\n📅 صلاحية المميز حتى: {stats['premium_until']}"
    else:
        text = "لا توجد إحصائيات بعد"

    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def recent_finds_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج آخر الأسماء المتاحة"""
    query = update.callback_query
    await query.answer()
    
    stats = db.get_global_stats()
    
    text = "🏆 **آخر الأسماء المتاحة:**\n\n"
    for i, name in enumerate(stats['recent_finds'], 1):
        text += f"{i}. @{name['username']}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def back_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الرجوع للقائمة الرئيسية"""
    query = update.callback_query
    await query.answer()
    
    is_admin = db.is_admin(update.effective_user.id)
    
    await query.edit_message_text(
        "🏠 **القائمة الرئيسية**\n\nاختر ما تريد:",
        reply_markup=get_main_keyboard(is_admin),
        parse_mode=ParseMode.MARKDOWN
    )

async def back_patterns_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الرجوع لقائمة الأنماط"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🎯 **اختر نمط التوليد:**",
        reply_markup=get_pattern_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def custom_count_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج العدد المخصص"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['awaiting_custom_count'] = True
    await query.edit_message_text("أرسل العدد المطلوب (1-10000):")

async def results_navigation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التنقل بين صفحات النتائج"""
    query = update.callback_query
    await query.answer()
    
    page = context.user_data.get('results_page', 0)
    
    if query.data == "results_next":
        context.user_data['results_page'] = page + 1
    elif query.data == "results_prev":
        context.user_data['results_page'] = max(0, page - 1)
    
    await view_all_results_handler(update, context)

async def broadcast_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد الإذاعة"""
    query = update.callback_query
    await query.answer()
    
    message = context.user_data.get('broadcast_message')
    if not message:
        await query.edit_message_text("❌ لا توجد رسالة للإذاعة")
        return
    
    # الحصول على جميع المستخدمين
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE is_banned = 0')
        users = cursor.fetchall()
    
    sent = 0
    failed = 0
    
    await query.edit_message_text(f"📢 جاري الإذاعة إلى {len(users)} مستخدم...")
    
    for user in users:
        try:
            await context.bot.send_message(
                user['user_id'],
                f"📢 **رسالة إدارية**\n\n{message}",
                parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
            await asyncio.sleep(0.05)  # تجنب حظر التردد
        except:
            failed += 1
    
    await query.edit_message_text(
        f"✅ **اكتملت الإذاعة**\n\n"
        f"تم الإرسال إلى: {sent}\n"
        f"فشل الإرسال إلى: {failed}"
    )

async def broadcast_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء الإذاعة"""
    query = update.callback_query
    await query.answer()
    
    context.user_data.pop('broadcast_message', None)
    
    await query.edit_message_text(
        "❌ تم إلغاء الإذاعة",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="admin_panel")
        ]])
    )

# ==================== تشغيل البوت ====================

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 بوت توليد وفحص الأسماء المميزة")
    print("=" * 50)
    print(f"📊 قاعدة البيانات: {config.DATABASE_FILE}")
    print(f"👑 المطور: {config.OWNER_ID}")
    print("=" * 50)
    
    if config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ خطأ: الرجاء وضع توكن البوت في ملف config.py")
        sys.exit(1)
    
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ: {e}")
