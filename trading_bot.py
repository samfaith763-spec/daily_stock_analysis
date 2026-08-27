import os
import requests
import json
from datetime import datetime
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.data.historical import StockHistoricalDataClient
from google import genai
from typing import Optional, Dict

class AutomatedTradingBot:
    def __init__(self):
        # Initialize Alpaca Trading Client
        self.alpaca_api_key = os.getenv('ALPACA_API_KEY')
        self.alpaca_secret = os.getenv('ALPACA_SECRET')
        self.ntfy_url = os.getenv('NTFY_URL')
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')
        self.stock_list = os.getenv('STOCK_LIST', '').split(',')
        
        # Initialize clients
        self.trading_client = TradingClient(self.alpaca_api_key, self.alpaca_secret)
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
            # Get current price and basic data
            account = self.trading_client.get_account()
            
            prompt = f"""
            Analyze this stock for trading: {symbol}
            
            Consider:
            1. Technical indicators (trend, momentum)
            2. Market sentiment
            3. Risk level
            4. Buy/Sell/Hold recommendation
            5. Entry and exit points
            
            Provide a concise analysis with a clear recommendation.
            """
            
            response = self.gemini_client.models.generate_content(
                model="gemini-pro",
                contents=prompt
            )
            
            return {
                "analysis": response.text,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            print(f"❌ Analysis error for {symbol}: {str(e)}")
            return {"analysis": f"Analysis failed: {str(e)}", "timestamp": datetime.now()}
    
    def execute_trade(self, symbol: str, side: str, quantity: int, order_type: str = "market"):
        """Execute a trade via Alpaca API"""
        try:
            # Check if market is open
            clock = self.trading_client.get_clock()
            if not clock.is_open:
                self.send_ntfy_notification(
                    "⚠️ Market Closed",
                    f"Cannot trade {symbol}. Market is closed."
                )
                return False
            
            # Create order parameters
            if order_type == "market":
                order_data = MarketOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=side,
                    time_in_force="day"
                )
            else:
                # For limit orders, you'd need to calculate the price
                order_data = LimitOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=side,
                    time_in_force="day",
                    limit_price=0.0  # You'd set this based on analysis
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
Type: {order_type.upper()}
Order ID: {order.id}

Status: ✅ Order Submitted Successfully
            """
            
            self.send_ntfy_notification(
                f"{'✅' if side == 'buy' else ''} Trade Executed: {symbol}",
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
    
    def make_trading_decision(self, symbol: str, analysis: str) -> Optional[str]:
        """Use Gemini to make trading decision based on analysis"""
        try:
            prompt = f"""
            Based on this analysis, should I BUY, SELL, or HOLD {symbol}?
            
            Analysis:
            {analysis}
            
            Respond with ONLY one word: BUY, SELL, or HOLD
            """
            
            response = self.gemini_client.models.generate_content(
                model="gemini-pro",
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
            " Trading Bot Started",
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
                positions = self.trading_client.get_all_positions()
                for pos in positions:
                    if pos.symbol == symbol and float(pos.qty) > 0:
                        self.execute_trade(symbol, "sell", quantity=int(float(pos.qty)))
                        break
            else:
                print(f"⏸️ Holding {symbol} - No action taken")
        
        self.send_ntfy_notification(
            "✅ Trading Cycle Complete",
            f"Finished analyzing {len(self.stock_list)} stocks",
            priority=3
        )
    
    def get_portfolio_status(self):
        """Get current portfolio status"""
        try:
            account = self.trading_client.get_account()
            positions = self.trading_client.get_all_positions()
            
            message = f"""
💼 PORTFOLIO STATUS

Cash: ${float(account.cash):,.2f}
Portfolio Value: ${float(account.portfolio_value):,.2f}
Equity: ${float(account.equity):,.2f}

Positions:
"""
            for pos in positions:
                if float(pos.qty) > 0:
                    message += f"\n{pos.symbol}: {pos.qty} shares @ ${float(pos.avg_entry_price):.2f}"
            
            self.send_ntfy_notification(
                "📊 Portfolio Update",
                message,
                priority=2
            )
            
        except Exception as e:
            print(f"❌ Error getting portfolio: {str(e)}")

# Main execution
if __name__ == "__main__":
    bot = AutomatedTradingBot()
    
    # Run the trading cycle
    bot.run_analysis_and_trade()
    
    # Optional: Get portfolio status
    # bot.get_portfolio_status()
