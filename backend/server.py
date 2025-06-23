from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timezone
import asyncio
import math

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Game Configuration
INITIAL_MINES = [
    {
        "id": 1,
        "name": "Basic Bitcoin Miner",
        "base_production": 1.0,  # coins per second
        "base_cost": 10.0,
        "upgrade_multiplier": 1.15,
        "manager_cost": 100.0,
        "unlocked": True,
        "description": "A simple cryptocurrency mining rig"
    },
    {
        "id": 2,
        "name": "Ethereum Farm",
        "base_production": 5.0,
        "base_cost": 100.0,
        "upgrade_multiplier": 1.15,
        "manager_cost": 1000.0,
        "unlocked": True,
        "description": "Industrial Ethereum mining facility"
    },
    {
        "id": 3,
        "name": "Altcoin Facility",
        "base_production": 25.0,
        "base_cost": 1000.0,
        "upgrade_multiplier": 1.15,
        "manager_cost": 10000.0,
        "unlocked": True,
        "description": "Advanced altcoin mining operation"
    },
    {
        "id": 4,
        "name": "Mining Warehouse",
        "base_production": 100.0,
        "base_cost": 12000.0,
        "upgrade_multiplier": 1.15,
        "manager_cost": 100000.0,
        "unlocked": False,
        "unlock_cost": 10000.0,
        "description": "Massive warehouse mining operation"
    },
    {
        "id": 5,
        "name": "Crypto Data Center",
        "base_production": 400.0,
        "base_cost": 100000.0,
        "upgrade_multiplier": 1.15,
        "manager_cost": 1000000.0,
        "unlocked": False,
        "unlock_cost": 100000.0,
        "description": "High-tech data center mining facility"
    }
]

# Define Models
class GameState(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    player_id: str = Field(default="default_player")
    currency: float = Field(default=0.0)
    ncg_tokens: float = Field(default=0.0)
    mines: Dict = Field(default_factory=dict)
    last_update: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_earnings: float = Field(default=0.0)

class MineState(BaseModel):
    mine_id: int
    level: int = Field(default=0)
    owned: bool = Field(default=False)
    has_manager: bool = Field(default=False)
    last_collection: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    unlocked: bool = Field(default=False)

class UpgradeRequest(BaseModel):
    mine_id: int

class PurchaseRequest(BaseModel):
    mine_id: int

class ConvertTokensRequest(BaseModel):
    amount: float

def calculate_mine_production(mine_config: dict, mine_state: MineState) -> float:
    """Calculate production rate for a mine"""
    if not mine_state.owned:
        return 0.0
    
    base_production = mine_config["base_production"]
    level_multiplier = mine_config["upgrade_multiplier"] ** mine_state.level
    manager_multiplier = 2.0 if mine_state.has_manager else 1.0
    
    return base_production * level_multiplier * manager_multiplier

def calculate_upgrade_cost(mine_config: dict, current_level: int) -> float:
    """Calculate cost to upgrade mine to next level"""
    base_cost = mine_config["base_cost"]
    return base_cost * (mine_config["upgrade_multiplier"] ** current_level)

async def get_or_create_game_state(player_id: str = "default_player") -> GameState:
    """Get existing game state or create new one"""
    existing_state = await db.game_states.find_one({"player_id": player_id})
    
    if existing_state:
        return GameState(**existing_state)
    
    # Create new game state
    new_state = GameState(player_id=player_id, currency=50.0)  # Start with some currency
    
    # Initialize mines
    for mine_config in INITIAL_MINES:
        mine_state = MineState(
            mine_id=mine_config["id"],
            unlocked=mine_config["unlocked"]
        )
        new_state.mines[str(mine_config["id"])] = mine_state.dict()
    
    await db.game_states.insert_one(new_state.dict())
    return new_state

async def update_game_state(game_state: GameState):
    """Update game state in database"""
    await db.game_states.update_one(
        {"player_id": game_state.player_id},
        {"$set": game_state.dict()}
    )

async def calculate_offline_income(game_state: GameState) -> float:
    """Calculate income earned while offline"""
    current_time = datetime.now(timezone.utc)
    time_away = (current_time - game_state.last_update).total_seconds()
    
    # Limit offline earnings to 24 hours
    time_away = min(time_away, 24 * 3600)
    
    total_income = 0.0
    
    for mine_id_str, mine_data in game_state.mines.items():
        mine_state = MineState(**mine_data)
        mine_id = int(mine_id_str)
        mine_config = next((m for m in INITIAL_MINES if m["id"] == mine_id), None)
        
        if mine_config and mine_state.owned and mine_state.has_manager:
            production_rate = calculate_mine_production(mine_config, mine_state)
            income = production_rate * time_away
            total_income += income
    
    return total_income

@api_router.get("/game/state")
async def get_game_state(player_id: str = "default_player"):
    """Get current game state"""
    game_state = await get_or_create_game_state(player_id)
    
    # Calculate offline income
    offline_income = await calculate_offline_income(game_state)
    if offline_income > 0:
        game_state.currency += offline_income
        game_state.total_earnings += offline_income
    
    # Update last update time
    game_state.last_update = datetime.now(timezone.utc)
    await update_game_state(game_state)
    
    # Add mine configurations for frontend
    mine_configs = {str(mine["id"]): mine for mine in INITIAL_MINES}
    
    return {
        "game_state": game_state,
        "mine_configs": mine_configs,
        "offline_income": offline_income
    }

@api_router.post("/game/purchase-mine")
async def purchase_mine(request: PurchaseRequest, player_id: str = "default_player"):
    """Purchase a mine"""
    game_state = await get_or_create_game_state(player_id)
    mine_config = next((m for m in INITIAL_MINES if m["id"] == request.mine_id), None)
    
    if not mine_config:
        raise HTTPException(status_code=404, detail="Mine not found")
    
    mine_state_data = game_state.mines.get(str(request.mine_id))
    if not mine_state_data:
        raise HTTPException(status_code=404, detail="Mine state not found")
    
    mine_state = MineState(**mine_state_data)
    
    # Check if mine is unlocked
    if not mine_state.unlocked and "unlock_cost" in mine_config:
        if game_state.currency < mine_config["unlock_cost"]:
            raise HTTPException(status_code=400, detail="Insufficient currency to unlock mine")
        
        game_state.currency -= mine_config["unlock_cost"]
        mine_state.unlocked = True
        game_state.mines[str(request.mine_id)] = mine_state.dict()
        await update_game_state(game_state)
        return {"message": "Mine unlocked successfully", "game_state": game_state}
    
    if mine_state.owned:
        raise HTTPException(status_code=400, detail="Mine already owned")
    
    cost = mine_config["base_cost"]
    if game_state.currency < cost:
        raise HTTPException(status_code=400, detail="Insufficient currency")
    
    game_state.currency -= cost
    mine_state.owned = True
    mine_state.last_collection = datetime.now(timezone.utc)
    
    game_state.mines[str(request.mine_id)] = mine_state.dict()
    await update_game_state(game_state)
    
    return {"message": "Mine purchased successfully", "game_state": game_state}

@api_router.post("/game/upgrade-mine")
async def upgrade_mine(request: UpgradeRequest, player_id: str = "default_player"):
    """Upgrade a mine"""
    game_state = await get_or_create_game_state(player_id)
    mine_config = next((m for m in INITIAL_MINES if m["id"] == request.mine_id), None)
    
    if not mine_config:
        raise HTTPException(status_code=404, detail="Mine not found")
    
    mine_state_data = game_state.mines.get(str(request.mine_id))
    if not mine_state_data:
        raise HTTPException(status_code=404, detail="Mine state not found")
    
    mine_state = MineState(**mine_state_data)
    
    if not mine_state.owned:
        raise HTTPException(status_code=400, detail="Mine not owned")
    
    upgrade_cost = calculate_upgrade_cost(mine_config, mine_state.level)
    if game_state.currency < upgrade_cost:
        raise HTTPException(status_code=400, detail="Insufficient currency")
    
    game_state.currency -= upgrade_cost
    mine_state.level += 1
    
    game_state.mines[str(request.mine_id)] = mine_state.dict()
    await update_game_state(game_state)
    
    return {"message": "Mine upgraded successfully", "game_state": game_state}

@api_router.post("/game/hire-manager")
async def hire_manager(request: UpgradeRequest, player_id: str = "default_player"):
    """Hire a manager for a mine"""
    game_state = await get_or_create_game_state(player_id)
    mine_config = next((m for m in INITIAL_MINES if m["id"] == request.mine_id), None)
    
    if not mine_config:
        raise HTTPException(status_code=404, detail="Mine not found")
    
    mine_state_data = game_state.mines.get(str(request.mine_id))
    if not mine_state_data:
        raise HTTPException(status_code=404, detail="Mine state not found")
    
    mine_state = MineState(**mine_state_data)
    
    if not mine_state.owned:
        raise HTTPException(status_code=400, detail="Mine not owned")
    
    if mine_state.has_manager:
        raise HTTPException(status_code=400, detail="Manager already hired")
    
    manager_cost = mine_config["manager_cost"]
    if game_state.currency < manager_cost:
        raise HTTPException(status_code=400, detail="Insufficient currency")
    
    game_state.currency -= manager_cost
    mine_state.has_manager = True
    
    game_state.mines[str(request.mine_id)] = mine_state.dict()
    await update_game_state(game_state)
    
    return {"message": "Manager hired successfully", "game_state": game_state}

@api_router.post("/game/collect-mine")
async def collect_mine(request: UpgradeRequest, player_id: str = "default_player"):
    """Manually collect from a mine"""
    game_state = await get_or_create_game_state(player_id)
    mine_config = next((m for m in INITIAL_MINES if m["id"] == request.mine_id), None)
    
    if not mine_config:
        raise HTTPException(status_code=404, detail="Mine not found")
    
    mine_state_data = game_state.mines.get(str(request.mine_id))
    if not mine_state_data:
        raise HTTPException(status_code=404, detail="Mine state not found")
    
    mine_state = MineState(**mine_state_data)
    
    if not mine_state.owned:
        raise HTTPException(status_code=400, detail="Mine not owned")
    
    # Calculate time since last collection
    current_time = datetime.now(timezone.utc)
    time_elapsed = (current_time - mine_state.last_collection).total_seconds()
    
    # Limit manual collection to 1 hour of production
    time_elapsed = min(time_elapsed, 3600)
    
    production_rate = calculate_mine_production(mine_config, mine_state)
    earnings = production_rate * time_elapsed
    
    game_state.currency += earnings
    game_state.total_earnings += earnings
    mine_state.last_collection = current_time
    
    game_state.mines[str(request.mine_id)] = mine_state.dict()
    await update_game_state(game_state)
    
    return {"message": f"Collected {earnings:.2f} coins", "earnings": earnings, "game_state": game_state}

@api_router.post("/game/convert-tokens")
async def convert_tokens(request: ConvertTokensRequest, player_id: str = "default_player"):
    """Convert currency to NCG tokens (10,000 currency = 1 NCG)"""
    game_state = await get_or_create_game_state(player_id)
    
    currency_needed = request.amount * 10000
    if game_state.currency < currency_needed:
        raise HTTPException(status_code=400, detail="Insufficient currency")
    
    game_state.currency -= currency_needed
    game_state.ncg_tokens += request.amount
    
    await update_game_state(game_state)
    
    return {"message": f"Converted {currency_needed:.0f} currency to {request.amount} NCG tokens", "game_state": game_state}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()