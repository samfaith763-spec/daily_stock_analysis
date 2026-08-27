import os
import requests
import json
from datetime import datetime
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.data.historical import StockHistoricalDataClient
from google import genai
from typing import Optional, Dict

class AutomatedTradingBot:
    def __init__(self):
        # Get environment variables
        self.alpaca_api_key = os.getenv('ALPACA_API_KEY')
        self.alpaca_secret = os.getenv('ALPACA_SECRET')
        self.ntfy_url = os.getenv('NTFY_URL')
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')
        self.stock_list = os.getenv('STOCK_LIST', '').split(',')
        
        # Validate credentials
        if not self.alpaca_api_key or not self.alpaca_secret:
            raise ValueError("Alpaca API credentials not found! Check your GitHub secrets.")
        
        if not self.gemini_api_key:
            raise ValueError("Gemini API key not found! Check your GitHub secrets.")
        
        if not self.ntfy_url:
            raise ValueError("NTFY_URL not found! Check your GitHub secrets.")
        
        # Initialize clients
        self.trading_client = TradingClient(self.alpaca_api_key, self.alpaca_secret, paper=True)
        self.data_client = StockHistoricalDataClient(self.alpaca_api_key, self.alpaca_secret)
        self.gemini_client = genai.Client(api_key=self.gemini_api_key)
        
    def send_ntfy_notification(self, title: str, message: str, priority: int = 3):
        """Send notification via ntfy"""
        try:
            response = requests.post(
                self.ntfy_url,
                data=message.encode('utf-8'),
                headers={
                    "Title": title,
                    "Priority": str(priority),
                    "Tags": "robot",
                    "Content-Type": "text/plain"
                }
            )
            if response.status_code == 200:
                print(f"✅ Notification sent: {title}")
            else:
                print(f"❌ Failed to send notification: {response.status_code}")
        except Exception as e:
            print(f" Error sending notification: {str(e)}")
    
    def get_stock_analysis(self, symbol: str) -> Dict:
        """Use Gemini API to analyze stock"""
        try:
            prompt = f"""
            Analyze this stock for trading: {symbol}
            
            Consider:
            1. Technical indicators (trend, momentum)
            2. Market sentiment
            3. Risk level
            4. Buy/Sell/Hold recommendation
            
            Provide a concise analysis with a clear recommendation.
            """
            
            response = self.gemini_client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt
            )
            
            return {
                "analysis": response.text,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            print(f"❌ Analysis error for {symbol}: {str(e)}")
            return {"analysis": f"Analysis failed: {str(e)}", "timestamp": datetime.now()}
    
    def execute_trade(self, symbol: str, side: str, quantity: int):
        """Execute a trade via Alpaca API"""
        try:
            # Check if market is open
            clock = self.trading_client.get_clock()
            if not clock.is_open:
                self.send_ntfy_notification(
                    "⚠️ Market Closed",
                    f"Cannot trade {symbol}. Market is closed.",
                    priority=4
                )
                return False
            
            # Create order parameters
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=side,
                time_in_force="day"
            )
            
            # Submit order
            order = self.trading_client.submit_order(order_data)
            
            # Send success notification
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"""
📊 TRADE EXECUTED

Time: {timestamp}
Symbol: {symbol}
Action: {side.upper()}
Quantity: {quantity}
Order ID: {order.id}

Status: ✅ Order Submitted Successfully
            """
            
            self.send_ntfy_notification(
                f"{'✅' if side == 'buy' else '💰'} Trade Executed: {symbol}",
                message,
                priority=4
            )
            
            return True
            
        except Exception as e:
            error_msg = f"""
❌ TRADE FAILED

Symbol: {symbol}
Action: {side.upper()}
Error: {str(e)}
            """
            
            self.send_ntfy_notification(
                f"❌ Trade Failed: {symbol}",
                error_msg,
                priority=5
            )
            return False
    
    def make_trading_decision(self, symbol: str, analysis: str) -> str:
        """Use Gemini to make trading decision based on analysis"""
        try:
            prompt = f"""
            Based on this analysis, should I BUY, SELL, or HOLD {symbol}?
            
            Analysis:
            {analysis}
            
            Respond with ONLY one word: BUY, SELL, or HOLD
            """
            
            response = self.gemini_client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt
            )
            
            decision = response.text.strip().upper()
            if "BUY" in decision:
                return "BUY"
            elif "SELL" in decision:
                return "SELL"
            else:
                return "HOLD"
                
        except Exception as e:
            print(f"❌ Decision error: {str(e)}")
            return "HOLD"
    
    def run_analysis_and_trade(self):
        """Main trading loop - analyze and execute trades"""
        self.send_ntfy_notification(
            "🤖 Trading Bot Started",
            f"Starting analysis for {len(self.stock_list)} stocks...",
            priority=3
        )
        
        for symbol in self.stock_list:
            symbol = symbol.strip()
            if not symbol:
                continue
                
            print(f"\n📈 Analyzing {symbol}...")
            
            # Get AI analysis
            analysis_result = self.get_stock_analysis(symbol)
            
            # Make trading decision
            decision = self.make_trading_decision(symbol, analysis_result["analysis"])
            
            # Log the decision
            print(f"Decision for {symbol}: {decision}")
            
            # Execute trade based on decision
            if decision == "BUY":
                # Buy 1 share (adjust quantity as needed)
                self.execute_trade(symbol, "buy", quantity=1)
            elif decision == "SELL":
                # Check if we own the stock first
                try:
                    positions = self.trading_client.get_all_positions()
                    for pos in positions:
                        if pos.symbol == symbol and float(pos.qty) > 0:
                            self.execute_trade(symbol, "sell", quantity=int(float(pos.qty)))
                            break
                except Exception as e:
                    print(f"Error checking positions: {e}")
            else:
                print(f"️ Holding {symbol} - No action taken")
        
        self.send_ntfy_notification(
            "✅ Trading Cycle Complete",
            f"Finished analyzing {len(self.stock_list)} stocks",
            priority=3
        )

# Main execution
if __name__ == "__main__":
    try:
        bot = AutomatedTradingBot()
        bot.run_analysis_and_trade()
    except ValueError as e:
        print(f"❌ CRITICAL ERROR: {str(e)}")
        print("Please check your GitHub repository secrets!")
        exit(1)
