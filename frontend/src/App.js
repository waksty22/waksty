import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import './App.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const formatCurrency = (amount) => {
  if (amount >= 1e12) return `${(amount / 1e12).toFixed(2)}T`;
  if (amount >= 1e9) return `${(amount / 1e9).toFixed(2)}B`;
  if (amount >= 1e6) return `${(amount / 1e6).toFixed(2)}M`;
  if (amount >= 1e3) return `${(amount / 1e3).toFixed(2)}K`;
  return amount.toFixed(2);
};

const MineCard = ({ mine, mineConfig, onPurchase, onUpgrade, onHireManager, onCollect, gameState }) => {
  const [isProcessing, setIsProcessing] = useState(false);
  
  const mineState = gameState?.mines?.[mine.id] || {};
  const isOwned = mineState.owned;
  const hasManager = mineState.has_manager;
  const level = mineState.level || 0;
  const isUnlocked = mineState.unlocked;
  
  const baseCost = mineConfig.base_cost;
  const upgradeCost = baseCost * Math.pow(mineConfig.upgrade_multiplier, level);
  const managerCost = mineConfig.manager_cost;
  const unlockCost = mineConfig.unlock_cost;
  
  const baseProduction = mineConfig.base_production;
  const levelMultiplier = Math.pow(mineConfig.upgrade_multiplier, level);
  const managerMultiplier = hasManager ? 2.0 : 1.0;
  const currentProduction = baseProduction * levelMultiplier * managerMultiplier;
  
  const handleAction = async (action, mineId) => {
    setIsProcessing(true);
    try {
      await action(mineId);
    } catch (error) {
      console.error('Action failed:', error);
    } finally {
      setIsProcessing(false);
    }
  };

  if (!isUnlocked && unlockCost) {
    return (
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 opacity-75">
        <div className="flex items-center mb-4">
          <div className="w-12 h-12 bg-gray-600 rounded-lg flex items-center justify-center mr-4">
            <span className="text-2xl">🔒</span>
          </div>
          <div>
            <h3 className="text-xl font-bold text-white">{mineConfig.name}</h3>
            <p className="text-gray-400 text-sm">{mineConfig.description}</p>
          </div>
        </div>
        
        <div className="space-y-3">
          <div className="text-center">
            <p className="text-gray-300 mb-2">Unlock Cost: {formatCurrency(unlockCost)} coins</p>
            <button
              onClick={() => handleAction(onPurchase, mine.id)}
              disabled={isProcessing || gameState.currency < unlockCost}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white px-4 py-2 rounded-lg font-semibold"
            >
              {isProcessing ? 'Unlocking...' : 'Unlock Mine'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gradient-to-br from-gray-800 to-gray-900 rounded-lg p-6 border border-gray-700 shadow-lg">
      <div className="flex items-center mb-4">
        <div className="w-12 h-12 bg-blue-600 rounded-lg flex items-center justify-center mr-4">
          <span className="text-2xl">⛏️</span>
        </div>
        <div>
          <h3 className="text-xl font-bold text-white">{mineConfig.name}</h3>
          <p className="text-gray-400 text-sm">{mineConfig.description}</p>
          {isOwned && (
            <p className="text-green-400 text-sm">Level {level} • {formatCurrency(currentProduction)}/sec</p>
          )}
        </div>
      </div>
      
      {!isOwned ? (
        <div className="space-y-3">
          <div className="text-center">
            <p className="text-gray-300 mb-2">Cost: {formatCurrency(baseCost)} coins</p>
            <button
              onClick={() => handleAction(onPurchase, mine.id)}
              disabled={isProcessing || gameState.currency < baseCost}
              className="w-full bg-green-600 hover:bg-green-700 disabled:bg-gray-600 text-white px-4 py-2 rounded-lg font-semibold"
            >
              {isProcessing ? 'Purchasing...' : 'Purchase Mine'}
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3">
            <button
              onClick={() => handleAction(onUpgrade, mine.id)}
              disabled={isProcessing || gameState.currency < upgradeCost}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white px-4 py-2 rounded-lg font-semibold"
            >
              {isProcessing ? 'Upgrading...' : `Upgrade (${formatCurrency(upgradeCost)})`}
            </button>
            
            {!hasManager && (
              <button
                onClick={() => handleAction(onHireManager, mine.id)}
                disabled={isProcessing || gameState.currency < managerCost}
                className="bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 text-white px-4 py-2 rounded-lg font-semibold"
              >
                {isProcessing ? 'Hiring...' : `Hire Manager (${formatCurrency(managerCost)})`}
              </button>
            )}
            
            {!hasManager && (
              <button
                onClick={() => handleAction(onCollect, mine.id)}
                disabled={isProcessing}
                className="bg-yellow-600 hover:bg-yellow-700 disabled:bg-gray-600 text-white px-4 py-2 rounded-lg font-semibold"
              >
                {isProcessing ? 'Collecting...' : 'Collect'}
              </button>
            )}
            
            {hasManager && (
              <div className="text-center text-green-400 font-semibold">
                ✅ Manager Active - Auto Collection
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

const TokenConverter = ({ gameState, onConvert }) => {
  const [convertAmount, setConvertAmount] = useState(1);
  const [isProcessing, setIsProcessing] = useState(false);
  
  const currencyNeeded = convertAmount * 10000;
  const canConvert = gameState.currency >= currencyNeeded;
  
  const handleConvert = async () => {
    setIsProcessing(true);
    try {
      await onConvert(convertAmount);
      setConvertAmount(1);
    } catch (error) {
      console.error('Conversion failed:', error);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="bg-gradient-to-br from-yellow-800 to-yellow-900 rounded-lg p-6 border border-yellow-600">
      <h3 className="text-xl font-bold text-yellow-100 mb-4 flex items-center">
        <span className="mr-2">🪙</span>
        NCG Token Converter
      </h3>
      
      <div className="space-y-4">
        <div>
          <p className="text-yellow-200 mb-2">Exchange Rate: 10,000 coins = 1 NCG</p>
          <p className="text-yellow-200">Your NCG Tokens: {formatCurrency(gameState.ncg_tokens || 0)}</p>
        </div>
        
        <div className="flex items-center space-x-4">
          <input
            type="number"
            min="1"
            value={convertAmount}
            onChange={(e) => setConvertAmount(Math.max(1, parseInt(e.target.value) || 1))}
            className="flex-1 bg-gray-700 text-white px-4 py-2 rounded-lg border border-gray-600"
            placeholder="NCG to buy"
          />
          <button
            onClick={handleConvert}
            disabled={!canConvert || isProcessing}
            className="bg-yellow-600 hover:bg-yellow-700 disabled:bg-gray-600 text-white px-6 py-2 rounded-lg font-semibold"
          >
            {isProcessing ? 'Converting...' : `Convert (${formatCurrency(currencyNeeded)})`}
          </button>
        </div>
      </div>
    </div>
  );
};

function App() {
  const [gameState, setGameState] = useState(null);
  const [mineConfigs, setMineConfigs] = useState({});
  const [offlineIncome, setOfflineIncome] = useState(0);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(Date.now());

  const fetchGameState = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/game/state`);
      setGameState(response.data.game_state);
      setMineConfigs(response.data.mine_configs);
      
      if (response.data.offline_income > 0) {
        setOfflineIncome(response.data.offline_income);
      }
      
      setLoading(false);
    } catch (error) {
      console.error('Failed to fetch game state:', error);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGameState();
  }, [fetchGameState]);

  // Auto-update currency for managed mines
  useEffect(() => {
    if (!gameState || !mineConfigs) return;

    const interval = setInterval(() => {
      const now = Date.now();
      const timeDiff = (now - lastUpdate) / 1000; // seconds
      
      let totalIncome = 0;
      
      Object.entries(gameState.mines).forEach(([mineId, mineData]) => {
        if (mineData.owned && mineData.has_manager) {
          const mineConfig = mineConfigs[mineId];
          if (mineConfig) {
            const baseProduction = mineConfig.base_production;
            const levelMultiplier = Math.pow(mineConfig.upgrade_multiplier, mineData.level || 0);
            const managerMultiplier = 2.0;
            const production = baseProduction * levelMultiplier * managerMultiplier;
            totalIncome += production * timeDiff;
          }
        }
      });

      if (totalIncome > 0) {
        setGameState(prev => ({
          ...prev,
          currency: prev.currency + totalIncome,
          total_earnings: prev.total_earnings + totalIncome
        }));
      }
      
      setLastUpdate(now);
    }, 1000);

    return () => clearInterval(interval);
  }, [gameState, mineConfigs, lastUpdate]);

  const handlePurchaseMine = async (mineId) => {
    try {
      await axios.post(`${API}/game/purchase-mine`, { mine_id: mineId });
      await fetchGameState();
    } catch (error) {
      console.error('Purchase failed:', error);
    }
  };

  const handleUpgradeMine = async (mineId) => {
    try {
      await axios.post(`${API}/game/upgrade-mine`, { mine_id: mineId });
      await fetchGameState();
    } catch (error) {
      console.error('Upgrade failed:', error);
    }
  };

  const handleHireManager = async (mineId) => {
    try {
      await axios.post(`${API}/game/hire-manager`, { mine_id: mineId });
      await fetchGameState();
    } catch (error) {
      console.error('Hire failed:', error);
    }
  };

  const handleCollectMine = async (mineId) => {
    try {
      const response = await axios.post(`${API}/game/collect-mine`, { mine_id: mineId });
      console.log(response.data.message);
      await fetchGameState();
    } catch (error) {
      console.error('Collection failed:', error);
    }
  };

  const handleConvertTokens = async (amount) => {
    try {
      await axios.post(`${API}/game/convert-tokens`, { amount });
      await fetchGameState();
    } catch (error) {
      console.error('Conversion failed:', error);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-white text-xl">Loading Crypto Miner Tycoon...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-blue-900 to-purple-900">
      {/* Header */}
      <div className="bg-black bg-opacity-50 backdrop-blur-sm border-b border-gray-700">
        <div className="container mx-auto px-4 py-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
                <span className="text-2xl">⛏️</span>
              </div>
              <div>
                <h1 className="text-3xl font-bold text-white">Crypto Miner Tycoon</h1>
                <p className="text-gray-400">Build your mining empire!</p>
              </div>
            </div>
            
            <div className="text-right">
              <div className="text-2xl font-bold text-green-400">
                💰 {formatCurrency(gameState?.currency || 0)} Coins
              </div>
              <div className="text-lg text-yellow-400">
                🪙 {formatCurrency(gameState?.ncg_tokens || 0)} NCG
              </div>
              <div className="text-sm text-gray-400">
                Total Earned: {formatCurrency(gameState?.total_earnings || 0)}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Offline Income Notification */}
      {offlineIncome > 0 && (
        <div className="bg-green-600 text-white p-4 text-center">
          Welcome back! You earned {formatCurrency(offlineIncome)} coins while away! 🎉
        </div>
      )}

      <div className="container mx-auto px-4 py-8">
        {/* Token Converter */}
        <div className="mb-8">
          <TokenConverter gameState={gameState} onConvert={handleConvertTokens} />
        </div>

        {/* Mines Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {Object.entries(mineConfigs || {}).map(([mineId, mineConfig]) => (
            <MineCard
              key={mineId}
              mine={{ id: mineId }}
              mineConfig={mineConfig}
              gameState={gameState}
              onPurchase={handlePurchaseMine}
              onUpgrade={handleUpgradeMine}
              onHireManager={handleHireManager}
              onCollect={handleCollectMine}
            />
          ))}
        </div>

        {/* Game Stats */}
        <div className="mt-8 bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h3 className="text-xl font-bold text-white mb-4">Empire Stats</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
            <div>
              <div className="text-2xl font-bold text-blue-400">
                {Object.values(gameState?.mines || {}).filter(m => m.owned).length}
              </div>
              <div className="text-gray-400">Mines Owned</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-purple-400">
                {Object.values(gameState?.mines || {}).filter(m => m.has_manager).length}
              </div>
              <div className="text-gray-400">Managers Hired</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-green-400">
                {Object.values(gameState?.mines || {}).reduce((sum, m) => sum + (m.level || 0), 0)}
              </div>
              <div className="text-gray-400">Total Upgrades</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-yellow-400">
                {formatCurrency(gameState?.total_earnings || 0)}
              </div>
              <div className="text-gray-400">Lifetime Earnings</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;