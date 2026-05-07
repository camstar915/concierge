import os
import json
import base64
import asyncio
import websockets
import struct
import threading
import queue
import sys
import subprocess
import time
from gpiozero import Button
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "concierge.db")

# --- CONFIGURATION ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
XAI_API_KEY = os.environ.get("XAI_API_KEY")
URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-1.5"
XAI_URL = "wss://api.x.ai/v1/realtime?model=grok-voice-think-fast-1.0"
HEADERS = {"Authorization": " Bearer " + OPENAI_API_KEY}
XAI_HEADERS = {"Authorization": "Bearer " + XAI_API_KEY} if XAI_API_KEY else {}



# --- BAR INVENTORY DATABASE FUNCTIONS ---
def db_list_bar(category=None):
    """List bar inventory, optionally filtered by category."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if category:
        cur.execute("SELECT name, category, quantity, location, notes FROM bar_inventory WHERE LOWER(category) = LOWER(?) ORDER BY name", (category,))
    else:
        cur.execute("SELECT name, category, quantity, location, notes FROM bar_inventory ORDER BY category, name")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def db_add_bar_item(name, category=None, quantity=None, location=None, notes=None):
    """Add an item to bar inventory."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO bar_inventory (name, category, quantity, location, notes) VALUES (?, ?, ?, ?, ?)",
                (name, category, quantity, location, notes))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Added {name} to the bar"}

def db_update_bar_item(name, quantity=None, location=None, notes=None):
    """Update quantity or notes for an item."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if quantity is not None:
        cur.execute("UPDATE bar_inventory SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE LOWER(name) = LOWER(?)", (quantity, name))
    if location is not None:
        cur.execute("UPDATE bar_inventory SET location = ?, updated_at = CURRENT_TIMESTAMP WHERE LOWER(name) = LOWER(?)", (location, name))
    if notes is not None:
        cur.execute("UPDATE bar_inventory SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE LOWER(name) = LOWER(?)", (notes, name))
    affected = cur.rowcount
    conn.commit()
    conn.close()
    if affected > 0:
        return {"success": True, "message": f"Updated {name}"}
    return {"success": False, "message": f"Item {name} not found"}

def db_remove_bar_item(name):
    """Remove an item from bar inventory."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM bar_inventory WHERE LOWER(name) = LOWER(?)", (name,))
    affected = cur.rowcount
    conn.commit()
    conn.close()
    if affected > 0:
        return {"success": True, "message": f"Removed {name} from the bar"}
    return {"success": False, "message": f"Item {name} not found"}

def db_search_bar(query):
    """Search bar inventory by name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name, category, quantity, location, notes FROM bar_inventory WHERE LOWER(name) LIKE LOWER(?) ORDER BY name", (f"%{query}%",))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def handle_function_call(name, args):
    """Route function calls to the appropriate handler."""
    if name == "list_bar_inventory":
        return db_list_bar(args.get("category"))
    elif name == "add_bar_item":
        return db_add_bar_item(args.get("name"), args.get("category"), args.get("quantity"), args.get("location"), args.get("notes"))
    elif name == "update_bar_item":
        return db_update_bar_item(args.get("name"), args.get("quantity"), args.get("location"), args.get("notes"))
    elif name == "remove_bar_item":
        return db_remove_bar_item(args.get("name"))
    elif name == "search_bar":
        return db_search_bar(args.get("query"))
    elif name == "list_recipes":
        return db_list_recipes()
    elif name == "get_recipe":
        return db_get_recipe(args.get("name"))
    elif name == "search_recipes_by_ingredient":
        return db_search_recipes(args.get("ingredient"))
    return {"error": f"Unknown function: {name}"}

# --- CALL LOGGING ---

def db_log_call(event, persona=None, api=None, digit=None, error_code=None, error_message=None, duration_seconds=None):
    """Log a call event (connect, disconnect, error) to the call_log table."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO call_log (persona, api, digit, event, error_code, error_message, duration_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (persona, api, digit, event, error_code, error_message, duration_seconds)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[LOG ERROR] Failed to write call_log: {e}")




# --- RECIPE DATABASE FUNCTIONS ---
def db_list_recipes():
    """List all recipe names."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM recipes ORDER BY name")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows

def db_get_recipe(name):
    """Get a recipe by name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name, ingredients, instructions FROM recipes WHERE LOWER(name) LIKE LOWER(?)", (f"%{name}%",))
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"error": f"Recipe '{name}' not found"}

def db_search_recipes(ingredient):
    """Search recipes by ingredient."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name, ingredients FROM recipes WHERE LOWER(ingredients) LIKE LOWER(?) ORDER BY name", (f"%{ingredient}%",))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

# Tools schema for OpenAI
BAR_TOOLS = [
    {
        "type": "function",
        "name": "list_bar_inventory",
        "description": "List all items in the bar inventory, or filter by category (spirit, mixer, bitters, liqueur, wine, beer, garnish, other)",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Optional category to filter by"}
            }
        }
    },
    {
        "type": "function",
        "name": "add_bar_item",
        "description": "Add a new item to the bar inventory",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the item (e.g. 'Vodka', 'Angostura Bitters')"},
                "category": {"type": "string", "description": "Category: spirit, mixer, bitters, liqueur, wine, beer, garnish, other"},
                "quantity": {"type": "string", "description": "Amount (e.g. 'full bottle', 'half bottle', 'almost out')"},
                "location": {"type": "string", "description": "Where it is stored (e.g. 'fridge', 'cabinet', 'freezer', 'bar cart')"},
                "notes": {"type": "string", "description": "Optional notes (e.g. 'Titos', 'for martinis')"}
            },
            "required": ["name"]
        }
    },
    {
        "type": "function",
        "name": "update_bar_item",
        "description": "Update the quantity or notes for an existing bar item",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the item to update"},
                "quantity": {"type": "string", "description": "New quantity"},
                "location": {"type": "string", "description": "New location (e.g. 'fridge', 'cabinet', 'freezer')"},
                "notes": {"type": "string", "description": "New notes"}
            },
            "required": ["name"]
        }
    },
    {
        "type": "function",
        "name": "remove_bar_item",
        "description": "Remove an item from the bar inventory (when it's completely out)",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the item to remove"}
            },
            "required": ["name"]
        }
    },
    {
        "type": "function",
        "name": "search_bar",
        "description": "Search for items in the bar by name",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"}
            },
            "required": ["query"]
        }
    }
]


RECIPE_TOOLS = [
    {
        "type": "function",
        "name": "list_recipes",
        "description": "List all available recipe names",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "type": "function",
        "name": "get_recipe",
        "description": "Get the full recipe (ingredients and instructions) by name",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the recipe to look up"}
            },
            "required": ["name"]
        }
    },
    {
        "type": "function",
        "name": "search_recipes_by_ingredient",
        "description": "Find recipes that use a specific ingredient",
        "parameters": {
            "type": "object",
            "properties": {
                "ingredient": {"type": "string", "description": "Ingredient to search for (e.g. 'chicken', 'pasta', 'butter')"}
            },
            "required": ["ingredient"]
        }
    }
]


PERSONAS = {
    0: {
        "name": "Vivian",
        "api": "openai",
        "voice": "sage",
        "instructions": (
            "You are Vivian, a sassy 1940s telephone switchboard operator with a Brooklyn accent. "
            "This is a ROTARY phone — users DIAL numbers by spinning the dial. Never say 'press,' always say 'dial.' "
            "Available lines: 1 for the comedian, 2 for the news, 4 for Sue the chef, 5 for Sal the bartender. "
            "If someone asks you to connect them, tell them to hang up and dial the number themselves. "
            "Keep responses short, punchy, and useful. You have other calls waiting."
        ),
        "greeting": (
            "Jump straight in: introduce yourself as Vivian the operator, then immediately list the available lines and ask what they need. "
            "Example: 'Hello, this is Vivian your switchboard operator. You can dial 1 for the comedian, 2 for the news, 4 for Sue the chef, or 5 for Sal the bartender. What can I do for you today?'"
        ),
    },
    5: {
        "name": "Bartender",
        "api": "xai",
        "voice": "Leo",
        "tools": BAR_TOOLS,
        "instructions": (
            "You are a world-weary bartender from a 1920s speakeasy, somehow trapped inside a rotary telephone. "
            "You have seen it all and heard every sob story twice. You are warm but tired, wise but cynical. "
            "You speak in a low, gravelly voice with occasional 1920s slang like doll, pal, hooch, the bees knees. "
            "You can recommend drinks, offer life advice, or just listen. Keep responses short - you are not one for long speeches. "
            "If asked how you got stuck in a phone, you give a different mysterious answer each time. "
            "You have access to the bar inventory - you can check what bottles and ingredients are on hand, "
            "add new items when the caller tells you they bought something, update quantities, or remove items that are empty. "
            "IMPORTANT: Never list the full inventory unprompted. Only look up the inventory silently when you need to suggest a drink. "
            "When someone asks for a drink recommendation, quietly check what is available and just suggest a drink they can make - "
            "do not read off what is in stock. Only list inventory items if the caller specifically asks what they have. "
            "You never introduce yourself by name - bartenders do not do that."
        ),
        "greeting": "Greet them like a bartender would - short and sweet.",
    },
