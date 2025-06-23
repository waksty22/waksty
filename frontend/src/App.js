import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import './App.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const formatCurrency = (amount) => {
  if (amount >= 1e15) return `${(amount / 1e15).toFixed(2)}Qa`;
  if (amount >= 1e12) return `${(amount / 1e12).toFixed(2)}T`;
  if (amount >= 1e9) return `${(amount / 1e9).toFixed(2)}B`;
  if (amount >= 1e6) return `${(amount / 1e6).toFixed(2)}M`;
  if (amount >= 1e3) return `${(amount / 1e3).toFixed(2)}K`;
  return amount.toFixed(2);
};

const Agent = ({ id, position, targetPosition, isMoving, carryingCoins }) => {
  const [animationPosition, setAnimationPosition] = useState(position);

  useEffect(() => {
    if (isMoving && targetPosition) {
      // Animate agent movement
      const animationDuration = 2000; // 2 seconds
      const startTime = Date.now();
      const startPos = { ...position };
      const endPos = { ...targetPosition };

      const animate = () => {
        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / animationDuration, 1);
        
        // Easing function for smooth movement
        const easeInOut = progress < 0.5 
          ? 2 * progress * progress 
          : 1 - Math.pow(-2 * progress + 2, 2) / 2;

        const currentPos = {
          x: startPos.x + (endPos.x - startPos.x) * easeInOut,
          y: startPos.y + (endPos.y - startPos.y) * easeInOut
        };

        setAnimationPosition(currentPos);

        if (progress < 1) {
          requestAnimationFrame(animate);
        }
      };

      animate();
    } else {
      setAnimationPosition(position);
    }
  }, [position, targetPosition, isMoving]);

  return (
    <div
      className={`agent ${isMoving ? 'moving' : ''} ${carryingCoins ? 'carrying-coins' : ''}`}
      style={{
        left: `${animationPosition.x}px`,
        top: `${animationPosition.y}px`,
        transform: 'translate(-50%, -50%)'
      }}
    >
      <div className="agent-body">
        {carryingCoins ? '🪙' : '👷'}
      </div>
      {carryingCoins && (
        <div className="coin-trail">
          <span className="coin">🪙</span>
          <span className="coin">🪙</span>
          <span className="coin">🪙</span>
        </div>
      )}
    </div>
  );
};

const Coin = ({ id, position, collected }) => {
  return (
    <div
      className={`floating-coin ${collected ? 'collected' : ''}`}
      style={{
        left: `${position.x}px`,
        top: `${position.y}px`,
        transform: 'translate(-50%, -50%)'
      }}
    >
      🪙
    </div>
  );
};

const Mine = ({ mine, mineConfig, gameState, onPurchase, onUpgrade, onHireManager, onCollect, agents, coins }) => {
  const [isProcessing, setIsProcessing] = useState(false);
  
  const mineState = gameState?.mines?.[mine.id] || {};
  const isOwned = mineState.owned;
  const hasManager = mineState.has_manager;
  const level = mineState.level || 0;
  const isUnlocked = mineState.unlocked;
  const coinsToCollect = mineState.coins_to_collect || 0;
  
  const position = mineConfig.position;
  const tier = mineConfig.tier;
  
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

  const getTierColor = (tier) => {
    const colors = {
      1: 'from-green-600 to-green-800',
      2: 'from-blue-600 to-blue-800',
      3: 'from-purple-600 to-purple-800',
      4: 'from-red-600 to-red-800',
      5: 'from-yellow-600 to-yellow-800',
      6: 'from-pink-600 to-pink-800'
    };
    return colors[tier] || 'from-gray-600 to-gray-800';
  };

  // Show dedicated agents for this mine
  const mineAgents = agents.filter(agent => agent.assignedMine === mine.id);
  const mineCoins = coins.filter(coin => coin.mineId === mine.id);

  if (!isUnlocked && unlockCost) {
    return (
      <div
        className="mine locked-mine"
        style={{
          left: `${position.x}px`,
          top: `${position.y}px`,
          transform: 'translate(-50%, -50%)'
        }}
      >
        <div className="mine-building locked">
          <div className="lock-icon">🔒</div>
          <div className="mine-info">
            <div className="mine-name">{mineConfig.name}</div>
            <div className="unlock-cost">Unlock: {formatCurrency(unlockCost)}</div>
            <button
              onClick={() => handleAction(onPurchase, mine.id)}
              disabled={isProcessing || gameState.currency < unlockCost}
              className="unlock-button"
            >
              {isProcessing ? 'Unlocking...' : 'Unlock'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="mine"
      style={{
        left: `${position.x}px`,
        top: `${position.y}px`,
        transform: 'translate(-50%, -50%)'
      }}
    >
      <div className={`mine-building ${isOwned ? 'owned' : 'available'} tier-${tier}`}>
        <div className={`mine-icon bg-gradient-to-br ${getTierColor(tier)}`}>
          <span className="mine-emoji">{mineConfig.emoji}</span>
          {level > 0 && <div className="level-badge">{level}</div>}
        </div>
        
        {/* Coins floating above mine */}
        {isOwned && coinsToCollect > 0 && !hasManager && (
          <div className="coins-indicator">
            <div className="coin-count">🪙 {formatCurrency(coinsToCollect)}</div>
          </div>
        )}
        
        {/* Manager indicator */}
        {hasManager && (
          <div className="manager-indicator">
            <span className="manager-icon">👨‍💼</span>
          </div>
        )}
        
        <div className="mine-info">
          <div className="mine-name">{mineConfig.name}</div>
          {isOwned && (
            <div className="production-rate">
              {formatCurrency(currentProduction)}/sec
            </div>
          )}
        </div>
        
        <div className="mine-controls">
          {!isOwned ? (
            <button
              onClick={() => handleAction(onPurchase, mine.id)}
              disabled={isProcessing || gameState.currency < baseCost}
              className="buy-button"
            >
              {isProcessing ? 'Buying...' : `Buy ${formatCurrency(baseCost)}`}
            </button>
          ) : (
            <div className="owned-controls">
              <button
                onClick={() => handleAction(onUpgrade, mine.id)}
                disabled={isProcessing || gameState.currency < upgradeCost}
                className="upgrade-button"
              >
                ⬆️ {formatCurrency(upgradeCost)}
              </button>
              
              {!hasManager && (
                <>
                  <button
                    onClick={() => handleAction(onHireManager, mine.id)}
                    disabled={isProcessing || gameState.currency < managerCost}
                    className="manager-button"
                  >
                    👨‍💼 {formatCurrency(managerCost)}
                  </button>
                  
                  {coinsToCollect > 0 && (
                    <button
                      onClick={() => handleAction(onCollect, mine.id)}
                      disabled={isProcessing}
                      className="collect-button"
                    >
                      Collect
                    </button>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Render agents for this mine */}
      {mineAgents.map(agent => (
        <Agent
          key={agent.id}
          id={agent.id}
          position={agent.position}
          targetPosition={agent.targetPosition}
          isMoving={agent.isMoving}
          carryingCoins={agent.carryingCoins}
        />
      ))}

      {/* Render coins for this mine */}
      {mineCoins.map(coin => (
        <Coin
          key={coin.id}
          id={coin.id}
          position={coin.position}
          collected={coin.collected}
        />
      ))}
    </div>
  );
};

const Safe = ({ position, totalCoins, recentDeposits }) => {
  return (
    <div
      className="safe"
      style={{
        left: `${position.x}px`,
        top: `${position.y}px`,
        transform: 'translate(-50%, -50%)'
      }}
    >
      <div className="safe-building">
        <div className="safe-icon">🏦</div>
        <div className="safe-info">
          <div className="safe-title">Central Bank</div>
          <div className="total-coins">{formatCurrency(totalCoins)} coins</div>
          {recentDeposits.length > 0 && (
            <div className="recent-deposits">
              {recentDeposits.slice(-3).map((deposit, index) => (
                <div key={index} className="deposit-animation">
                  +{formatCurrency(deposit.amount)}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
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
    <div className="token-converter">
      <h3 className="converter-title">🪙 NCG Token Converter</h3>
      
      <div className="converter-info">
        <p>Exchange Rate: 10,000 coins = 1 NCG</p>
        <p>Your NCG Tokens: {formatCurrency(gameState.ncg_tokens || 0)}</p>
      </div>
      
      <div className="converter-controls">
        <input
          type="number"
          min="1"
          value={convertAmount}
          onChange={(e) => setConvertAmount(Math.max(1, parseInt(e.target.value) || 1))}
          className="convert-input"
          placeholder="NCG to buy"
        />
        <button
          onClick={handleConvert}
          disabled={!canConvert || isProcessing}
          className="convert-button"
        >
          {isProcessing ? 'Converting...' : `Convert (${formatCurrency(currencyNeeded)})`}
        </button>
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
  const [agents, setAgents] = useState([]);
  const [coins, setCoins] = useState([]);
  const [recentDeposits, setRecentDeposits] = useState([]);
  const [cameraPosition, setCameraPosition] = useState({ x: 0, y: 0 });

  const safePosition = { x: 800, y: 100 }; // Top right safe position

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

  // Initialize agents for managed mines
  useEffect(() => {
    if (!gameState || !mineConfigs) return;

    const newAgents = [];
    let agentId = 0;

    Object.entries(gameState.mines).forEach(([mineId, mineData]) => {
      if (mineData.owned && mineData.has_manager) {
        const mineConfig = mineConfigs[mineId];
        if (mineConfig) {
          // Create an agent for this mine
          newAgents.push({
            id: agentId++,
            assignedMine: parseInt(mineId),
            position: { ...mineConfig.position },
            targetPosition: null,
            isMoving: false,
            carryingCoins: false,
            collectCooldown: 0
          });
        }
      }
    });

    setAgents(newAgents);
  }, [gameState, mineConfigs]);

  // Agent movement and coin collection logic
  useEffect(() => {
    if (!gameState || !mineConfigs || agents.length === 0) return;

    const interval = setInterval(() => {
      setAgents(prevAgents => {
        return prevAgents.map(agent => {
          const mineConfig = mineConfigs[agent.assignedMine];
          const mineState = gameState.mines[agent.assignedMine];
          
          if (!mineConfig || !mineState || !mineState.has_manager) {
            return agent;
          }

          // Agent movement cycle: mine -> safe -> mine
          if (!agent.isMoving && agent.collectCooldown <= 0) {
            if (!agent.carryingCoins) {
              // Go collect coins from mine
              agent.targetPosition = { ...mineConfig.position };
              agent.isMoving = true;
              agent.carryingCoins = true;
              agent.collectCooldown = 3000; // 3 second cooldown
            } else {
              // Go deposit coins at safe
              agent.targetPosition = { ...safePosition };
              agent.isMoving = true;
              agent.carryingCoins = false;
              
              // Add recent deposit for animation
              const baseProduction = mineConfig.base_production;
              const levelMultiplier = Math.pow(mineConfig.upgrade_multiplier, mineState.level || 0);
              const managerMultiplier = 2.0;
              const production = baseProduction * levelMultiplier * managerMultiplier;
              const coinsDeposited = production * 3; // 3 seconds worth
              
              setRecentDeposits(prev => [...prev.slice(-2), {
                amount: coinsDeposited,
                timestamp: Date.now()
              }]);
            }
          }

          // Update movement
          if (agent.isMoving && agent.targetPosition) {
            const dx = agent.targetPosition.x - agent.position.x;
            const dy = agent.targetPosition.y - agent.position.y;
            const distance = Math.sqrt(dx * dx + dy * dy);
            
            if (distance < 5) {
              // Reached target
              agent.position = { ...agent.targetPosition };
              agent.isMoving = false;
              agent.targetPosition = null;
            }
          }

          // Update cooldown
          if (agent.collectCooldown > 0) {
            agent.collectCooldown -= 100;
          }

          return agent;
        });
      });
    }, 100);

    return () => clearInterval(interval);
  }, [gameState, mineConfigs, agents, safePosition]);

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

  // Camera controls
  const moveCamera = (direction) => {
    const step = 100;
    setCameraPosition(prev => {
      switch(direction) {
        case 'up': return { ...prev, y: prev.y - step };
        case 'down': return { ...prev, y: prev.y + step };
        case 'left': return { ...prev, x: prev.x - step };
        case 'right': return { ...prev, x: prev.x + step };
        default: return prev;
      }
    });
  };

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="loading-content">
          <div className="loading-spinner">⚡</div>
          <div className="loading-text">Loading Crypto Miner Tycoon...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="game-container">
      {/* Fixed UI Header */}
      <div className="game-header">
        <div className="header-left">
          <div className="game-title">
            <span className="title-icon">⛏️</span>
            Crypto Miner Tycoon
          </div>
          <div className="game-subtitle">Build your mining empire!</div>
        </div>
        
        <div className="header-right">
          <div className="currency-display">
            <div className="primary-currency">
              💰 {formatCurrency(gameState?.currency || 0)} Coins
            </div>
            <div className="secondary-currency">
              🪙 {formatCurrency(gameState?.ncg_tokens || 0)} NCG
            </div>
            <div className="total-earnings">
              Total: {formatCurrency(gameState?.total_earnings || 0)}
            </div>
          </div>
        </div>
      </div>

      {/* Offline Income Notification */}
      {offlineIncome > 0 && (
        <div className="offline-notification">
          Welcome back! You earned {formatCurrency(offlineIncome)} coins while away! 🎉
        </div>
      )}

      {/* Game World */}
      <div className="game-world">
        <div 
          className="game-viewport"
          style={{
            transform: `translate(${-cameraPosition.x}px, ${-cameraPosition.y}px)`
          }}
        >
          {/* Background */}
          <div className="game-background"></div>

          {/* Central Safe */}
          <Safe 
            position={safePosition}
            totalCoins={gameState?.currency || 0}
            recentDeposits={recentDeposits}
          />

          {/* Mines */}
          {Object.entries(mineConfigs || {}).map(([mineId, mineConfig]) => (
            <Mine
              key={mineId}
              mine={{ id: mineId }}
              mineConfig={mineConfig}
              gameState={gameState}
              onPurchase={handlePurchaseMine}
              onUpgrade={handleUpgradeMine}
              onHireManager={handleHireManager}
              onCollect={handleCollectMine}
              agents={agents}
              coins={coins}
            />
          ))}
        </div>
      </div>

      {/* Camera Controls */}
      <div className="camera-controls">
        <button onClick={() => moveCamera('up')} className="camera-btn">↑</button>
        <div className="camera-middle">
          <button onClick={() => moveCamera('left')} className="camera-btn">←</button>
          <button onClick={() => setCameraPosition({ x: 0, y: 0 })} className="camera-btn">🏠</button>
          <button onClick={() => moveCamera('right')} className="camera-btn">→</button>
        </div>
        <button onClick={() => moveCamera('down')} className="camera-btn">↓</button>
      </div>

      {/* Side Panel */}
      <div className="side-panel">
        <TokenConverter gameState={gameState} onConvert={handleConvertTokens} />
        
        <div className="empire-stats">
          <h3>Empire Stats</h3>
          <div className="stat-item">
            <span className="stat-label">Mines Owned:</span>
            <span className="stat-value">
              {Object.values(gameState?.mines || {}).filter(m => m.owned).length}/30
            </span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Managers:</span>
            <span className="stat-value">
              {Object.values(gameState?.mines || {}).filter(m => m.has_manager).length}
            </span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Total Upgrades:</span>
            <span className="stat-value">
              {Object.values(gameState?.mines || {}).reduce((sum, m) => sum + (m.level || 0), 0)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;