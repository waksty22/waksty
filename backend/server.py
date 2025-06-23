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

# All 30 Mines Configuration - Vertical Layout
ALL_MINES = [
    # Tier 1: Basic Crypto Mines (1-5)
    {"id": 1, "name": "Bitcoin Starter", "base_production": 1.0, "base_cost": 10.0, "upgrade_multiplier": 1.15, "manager_cost": 100.0, "unlocked": True, "description": "Basic Bitcoin mining rig", "emoji": "₿", "tier": 1, "position": {"x": 300, "y": 150}},
    {"id": 2, "name": "Ethereum Farm", "base_production": 5.0, "base_cost": 100.0, "upgrade_multiplier": 1.15, "manager_cost": 1000.0, "unlocked": True, "description": "Ethereum mining facility", "emoji": "⟠", "tier": 1, "position": {"x": 300, "y": 250}},
    {"id": 3, "name": "Litecoin Mine", "base_production": 25.0, "base_cost": 1000.0, "upgrade_multiplier": 1.15, "manager_cost": 10000.0, "unlocked": True, "description": "Litecoin mining operation", "emoji": "Ł", "tier": 1, "position": {"x": 300, "y": 350}},
    {"id": 4, "name": "Dogecoin Dig", "base_production": 100.0, "base_cost": 12000.0, "upgrade_multiplier": 1.15, "manager_cost": 100000.0, "unlocked": False, "unlock_cost": 5000.0, "description": "Much mining, very wow", "emoji": "🐕", "tier": 1, "position": {"x": 300, "y": 450}},
    {"id": 5, "name": "Cardano Station", "base_production": 400.0, "base_cost": 100000.0, "upgrade_multiplier": 1.15, "manager_cost": 1000000.0, "unlocked": False, "unlock_cost": 50000.0, "description": "Cardano staking pool", "emoji": "₳", "tier": 1, "position": {"x": 300, "y": 550}},
    
    # Tier 2: Advanced Crypto Operations (6-10)
    {"id": 6, "name": "Polygon Network", "base_production": 1600.0, "base_cost": 800000.0, "upgrade_multiplier": 1.15, "manager_cost": 8000000.0, "unlocked": False, "unlock_cost": 400000.0, "description": "Polygon scaling solution", "emoji": "🔷", "tier": 2, "position": {"x": 300, "y": 650}},
    {"id": 7, "name": "Solana Cluster", "base_production": 6400.0, "base_cost": 6400000.0, "upgrade_multiplier": 1.15, "manager_cost": 64000000.0, "unlocked": False, "unlock_cost": 3200000.0, "description": "High-speed Solana validator", "emoji": "◉", "tier": 2, "position": {"x": 300, "y": 750}},
    {"id": 8, "name": "Avalanche Peak", "base_production": 25600.0, "base_cost": 51200000.0, "upgrade_multiplier": 1.15, "manager_cost": 512000000.0, "unlocked": False, "unlock_cost": 25600000.0, "description": "Avalanche consensus network", "emoji": "🏔️", "tier": 2, "position": {"x": 300, "y": 850}},
    {"id": 9, "name": "Chainlink Oracle", "base_production": 102400.0, "base_cost": 409600000.0, "upgrade_multiplier": 1.15, "manager_cost": 4096000000.0, "unlocked": False, "unlock_cost": 204800000.0, "description": "Decentralized oracle network", "emoji": "🔗", "tier": 2, "position": {"x": 300, "y": 950}},
    {"id": 10, "name": "Cosmos Hub", "base_production": 409600.0, "base_cost": 3276800000.0, "upgrade_multiplier": 1.15, "manager_cost": 32768000000.0, "unlocked": False, "unlock_cost": 1638400000.0, "description": "Internet of blockchains", "emoji": "⚛️", "tier": 2, "position": {"x": 300, "y": 1050}},
    
    # Tier 3: Industrial Facilities (11-15)
    {"id": 11, "name": "Mining Warehouse", "base_production": 1638400.0, "base_cost": 26214400000.0, "upgrade_multiplier": 1.15, "manager_cost": 262144000000.0, "unlocked": False, "unlock_cost": 13107200000.0, "description": "Massive mining warehouse", "emoji": "🏭", "tier": 3, "position": {"x": 300, "y": 1150}},
    {"id": 12, "name": "Hydro Power Plant", "base_production": 6553600.0, "base_cost": 209715200000.0, "upgrade_multiplier": 1.15, "manager_cost": 2097152000000.0, "unlocked": False, "unlock_cost": 104857600000.0, "description": "Renewable energy mining", "emoji": "💧", "tier": 3, "position": {"x": 300, "y": 1250}},
    {"id": 13, "name": "Solar Farm Complex", "base_production": 26214400.0, "base_cost": 1677721600000.0, "upgrade_multiplier": 1.15, "manager_cost": 16777216000000.0, "unlocked": False, "unlock_cost": 838860800000.0, "description": "Solar-powered mining farm", "emoji": "☀️", "tier": 3, "position": {"x": 300, "y": 1350}},
    {"id": 14, "name": "Geothermal Station", "base_production": 104857600.0, "base_cost": 13421772800000.0, "upgrade_multiplier": 1.15, "manager_cost": 134217728000000.0, "unlocked": False, "unlock_cost": 6710886400000.0, "description": "Geothermal energy mining", "emoji": "🌋", "tier": 3, "position": {"x": 300, "y": 1450}},
    {"id": 15, "name": "Nuclear Reactor", "base_production": 419430400.0, "base_cost": 107374182400000.0, "upgrade_multiplier": 1.15, "manager_cost": 1073741824000000.0, "unlocked": False, "unlock_cost": 53687091200000.0, "description": "Nuclear-powered mining", "emoji": "⚛️", "tier": 3, "position": {"x": 300, "y": 1550}},
    
    # Tier 4: High-Tech Data Centers (16-20)
    {"id": 16, "name": "Quantum Computer", "base_production": 1677721600.0, "base_cost": 858993459200000.0, "upgrade_multiplier": 1.15, "manager_cost": 8589934592000000.0, "unlocked": False, "unlock_cost": 429496729600000.0, "description": "Quantum computing cluster", "emoji": "🔬", "tier": 4, "position": {"x": 300, "y": 1650}},
    {"id": 17, "name": "AI Processing Center", "base_production": 6710886400.0, "base_cost": 6871947673600000.0, "upgrade_multiplier": 1.15, "manager_cost": 68719476736000000.0, "unlocked": False, "unlock_cost": 3435973836800000.0, "description": "AI-powered mining optimization", "emoji": "🤖", "tier": 4, "position": {"x": 300, "y": 1750}},
    {"id": 18, "name": "Supercomputer Array", "base_production": 26843545600.0, "base_cost": 54975581388800000.0, "upgrade_multiplier": 1.15, "manager_cost": 549755813888000000.0, "unlocked": False, "unlock_cost": 27487790694400000.0, "description": "Supercomputer mining array", "emoji": "🖥️", "tier": 4, "position": {"x": 300, "y": 1850}},
    {"id": 19, "name": "Blockchain Foundry", "base_production": 107374182400.0, "base_cost": 439804651110400000.0, "upgrade_multiplier": 1.15, "manager_cost": 4398046511104000000.0, "unlocked": False, "unlock_cost": 219902325555200000.0, "description": "Next-gen blockchain forge", "emoji": "⚒️", "tier": 4, "position": {"x": 300, "y": 1950}},
    {"id": 20, "name": "Metaverse Engine", "base_production": 429496729600.0, "base_cost": 3518437208883200000.0, "upgrade_multiplier": 1.15, "manager_cost": 35184372088832000000.0, "unlocked": False, "unlock_cost": 1759218604441600000.0, "description": "Virtual world mining engine", "emoji": "🌐", "tier": 4, "position": {"x": 300, "y": 2050}},
    
    # Tier 5: Future Tech (21-25)
    {"id": 21, "name": "Fusion Reactor", "base_production": 1717986918400.0, "base_cost": 28147497671065600000.0, "upgrade_multiplier": 1.15, "manager_cost": 281474976710656000000.0, "unlocked": False, "unlock_cost": 14073748835532800000.0, "description": "Fusion-powered mining", "emoji": "🔥", "tier": 5, "position": {"x": 300, "y": 2150}},
    {"id": 22, "name": "Antimatter Engine", "base_production": 6871947673600.0, "base_cost": 225179981368524800000.0, "upgrade_multiplier": 1.15, "manager_cost": 2251799813685248000000.0, "unlocked": False, "unlock_cost": 112589990684262400000.0, "description": "Antimatter energy mining", "emoji": "💥", "tier": 5, "position": {"x": 300, "y": 2250}},
    {"id": 23, "name": "Time Dilator", "base_production": 27487790694400.0, "base_cost": 1801439850948198400000.0, "upgrade_multiplier": 1.15, "manager_cost": 18014398509481984000000.0, "unlocked": False, "unlock_cost": 900719925474099200000.0, "description": "Time manipulation mining", "emoji": "⏰", "tier": 5, "position": {"x": 300, "y": 2350}},
    {"id": 24, "name": "Wormhole Generator", "base_production": 109951162777600.0, "base_cost": 14411518807585587200000.0, "upgrade_multiplier": 1.15, "manager_cost": 144115188075855872000000.0, "unlocked": False, "unlock_cost": 7205759403792793600000.0, "description": "Interdimensional mining", "emoji": "🌌", "tier": 5, "position": {"x": 300, "y": 2450}},
    {"id": 25, "name": "Reality Processor", "base_production": 439804651110400.0, "base_cost": 115292150460684697600000.0, "upgrade_multiplier": 1.15, "manager_cost": 1152921504606846976000000.0, "unlocked": False, "unlock_cost": 57646075230342348800000.0, "description": "Reality-bending mining rig", "emoji": "✨", "tier": 5, "position": {"x": 300, "y": 2550}},
    
    # Tier 6: Space Mining (26-30)
    {"id": 26, "name": "Moon Base Alpha", "base_production": 1759218604441600.0, "base_cost": 922337203685477580800000.0, "upgrade_multiplier": 1.15, "manager_cost": 9223372036854775808000000.0, "unlocked": False, "unlock_cost": 461168601842738790400000.0, "description": "Lunar mining outpost", "emoji": "🌙", "tier": 6, "position": {"x": 300, "y": 2650}},
    {"id": 27, "name": "Mars Colony", "base_production": 7036874417766400.0, "base_cost": 7378697629483820646400000.0, "upgrade_multiplier": 1.15, "manager_cost": 73786976294838206464000000.0, "unlocked": False, "unlock_cost": 3689348814741910323200000.0, "description": "Martian mining colony", "emoji": "🔴", "tier": 6, "position": {"x": 300, "y": 2750}},
    {"id": 28, "name": "Asteroid Belt", "base_production": 28147497671065600.0, "base_cost": 59029581035870565171200000.0, "upgrade_multiplier": 1.15, "manager_cost": 590295810358705651712000000.0, "unlocked": False, "unlock_cost": 29514790517935282585600000.0, "description": "Asteroid mining operation", "emoji": "☄️", "tier": 6, "position": {"x": 300, "y": 2850}},
    {"id": 29, "name": "Jupiter Station", "base_production": 112589990684262400.0, "base_cost": 472236648286964521369600000.0, "upgrade_multiplier": 1.15, "manager_cost": 4722366482869645213696000000.0, "unlocked": False, "unlock_cost": 236118324143482260684800000.0, "description": "Gas giant mining platform", "emoji": "🪐", "tier": 6, "position": {"x": 300, "y": 2950}},
    {"id": 30, "name": "Galactic Core", "base_production": 450359962737049600.0, "base_cost": 3777893186295716170956800000.0, "upgrade_multiplier": 1.15, "manager_cost": 37778931862957161709568000000.0, "unlocked": False, "unlock_cost": 1888946593147858085478400000.0, "description": "Ultimate cosmic mining station", "emoji": "🌌", "tier": 6, "position": {"x": 300, "y": 3050}}
]

# Define Models
class GameState(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    player_id: str = Field(default="default_player")
    currency: float = Field(default=0.0)
    ncg_tokens: float = Field(default=0.0)
    mines: Dict = Field(default_factory=dict)
    last_update: datetime = Field(default_factory=datetime.utcnow)
    total_earnings: float = Field(default=0.0)

class MineState(BaseModel):
    mine_id: int
    level: int = Field(default=0)
    owned: bool = Field(default=False)
    has_manager: bool = Field(default=False)
    last_collection: datetime = Field(default_factory=datetime.utcnow)
    unlocked: bool = Field(default=False)
    coins_to_collect: float = Field(default=0.0)

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
        # Ensure all 30 mines are present (backward compatibility)
        game_state = GameState(**existing_state)
        missing_mines = []
        
        for mine_config in ALL_MINES:
            mine_id_str = str(mine_config["id"])
            if mine_id_str not in game_state.mines:
                missing_mines.append(mine_config)
        
        if missing_mines:
            # Add missing mines
            for mine_config in missing_mines:
                mine_state = MineState(
                    mine_id=mine_config["id"],
                    unlocked=mine_config["unlocked"]
                )
                game_state.mines[str(mine_config["id"])] = mine_state.dict()
            
            # Update database
            await update_game_state(game_state)
        
        return game_state
    
    # Create new game state
    new_state = GameState(player_id=player_id, currency=50.0)  # Start with some currency
    
    # Initialize mines
    for mine_config in ALL_MINES:
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
    current_time = datetime.utcnow()
    time_away = (current_time - game_state.last_update).total_seconds()
    
    # Limit offline earnings to 24 hours
    time_away = min(time_away, 24 * 3600)
    
    total_income = 0.0
    
    for mine_id_str, mine_data in game_state.mines.items():
        mine_state = MineState(**mine_data)
        mine_id = int(mine_id_str)
        mine_config = next((m for m in ALL_MINES if m["id"] == mine_id), None)
        
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
    
    # Update coin accumulation for owned mines
    current_time = datetime.utcnow()
    for mine_id_str, mine_data in game_state.mines.items():
        mine_state = MineState(**mine_data)
        mine_id = int(mine_id_str)
        mine_config = next((m for m in ALL_MINES if m["id"] == mine_id), None)
        
        if mine_config and mine_state.owned:
            time_since_collection = (current_time - mine_state.last_collection).total_seconds()
            production_rate = calculate_mine_production(mine_config, mine_state)
            
            # Calculate coins to collect (limit to 1 hour for non-managed mines)
            if not mine_state.has_manager:
                time_since_collection = min(time_since_collection, 3600)
            
            coins_generated = production_rate * time_since_collection
            mine_state.coins_to_collect = coins_generated
            game_state.mines[mine_id_str] = mine_state.dict()
    
    # Update last update time
    game_state.last_update = current_time
    await update_game_state(game_state)
    
    # Add mine configurations for frontend
    mine_configs = {str(mine["id"]): mine for mine in ALL_MINES}
    
    return {
        "game_state": game_state,
        "mine_configs": mine_configs,
        "offline_income": offline_income
    }

@api_router.post("/game/purchase-mine")
async def purchase_mine(request: PurchaseRequest, player_id: str = "default_player"):
    """Purchase a mine"""
    game_state = await get_or_create_game_state(player_id)
    mine_config = next((m for m in ALL_MINES if m["id"] == request.mine_id), None)
    
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
    mine_state.last_collection = datetime.utcnow()
    
    game_state.mines[str(request.mine_id)] = mine_state.dict()
    await update_game_state(game_state)
    
    return {"message": "Mine purchased successfully", "game_state": game_state}

@api_router.post("/game/upgrade-mine")
async def upgrade_mine(request: UpgradeRequest, player_id: str = "default_player"):
    """Upgrade a mine"""
    game_state = await get_or_create_game_state(player_id)
    mine_config = next((m for m in ALL_MINES if m["id"] == request.mine_id), None)
    
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
    mine_config = next((m for m in ALL_MINES if m["id"] == request.mine_id), None)
    
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
    mine_config = next((m for m in ALL_MINES if m["id"] == request.mine_id), None)
    
    if not mine_config:
        raise HTTPException(status_code=404, detail="Mine not found")
    
    mine_state_data = game_state.mines.get(str(request.mine_id))
    if not mine_state_data:
        raise HTTPException(status_code=404, detail="Mine state not found")
    
    mine_state = MineState(**mine_state_data)
    
    if not mine_state.owned:
        raise HTTPException(status_code=400, detail="Mine not owned")
    
    # Get the coins to collect
    earnings = mine_state.coins_to_collect
    
    game_state.currency += earnings
    game_state.total_earnings += earnings
    mine_state.last_collection = datetime.utcnow()
    mine_state.coins_to_collect = 0.0
    
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