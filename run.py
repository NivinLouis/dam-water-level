"""
Dam Water Level Monitoring System - Single Command Launcher
Run this file to start the server and open the dashboard.
"""

import subprocess
import sys
import webbrowser
import time
import threading
import os

def open_browser():
    """Open browser after a short delay to let server start."""
    time.sleep(2)
    webbrowser.open('http://localhost:5000/')

def main():
    print("=" * 50)
    print("   Dam Water Level Monitoring System")
    print("=" * 50)
    print()
    print("Starting server and opening dashboard...")
    print("Dashboard: http://localhost:5000/")
    print()
    print("Press Ctrl+C to stop the server")
    print("=" * 50)
    print()
    
    # Open browser in background thread
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    # Change to script directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # Run the Flask app
    try:
        from app import app, socketio
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\nServer stopped.")

if __name__ == '__main__':
    main()
