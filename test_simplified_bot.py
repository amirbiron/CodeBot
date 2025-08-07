#!/usr/bin/env python3
"""
Basic functionality test for the simplified CodeBot
"""

import os
import sys

def test_basic_functionality():
    """Test that the simplified bot can be created and has basic functionality"""
    
    # Set dummy environment variables
    os.environ['BOT_TOKEN'] = 'dummy_token_for_testing'
    os.environ['MONGODB_URL'] = 'dummy_mongo_uri'
    
    try:
        # Test imports
        print("🔍 Testing imports...")
        import activity_reporter
        print("  ✅ activity_reporter imported")
        
        import conversation_handlers
        print("  ✅ conversation_handlers imported")
        
        from main import SimpleCodeKeeperBot
        print("  ✅ SimpleCodeKeeperBot imported")
        
        # Test basic bot creation
        print("\n🔍 Testing bot creation...")
        bot = SimpleCodeKeeperBot()
        print("  ✅ Bot instance created")
        
        # Test handler setup
        print("\n🔍 Testing handlers...")
        handler_count = len(bot.application.handlers)
        print(f"  ✅ {handler_count} handlers registered")
        
        # Test conversation handler structure
        conv_handler = None
        for handler in bot.application.handlers:
            if hasattr(handler, 'entry_points'):
                conv_handler = handler
                break
        
        if conv_handler:
            entry_points = len(conv_handler.entry_points)
            states = len(conv_handler.states)
            fallbacks = len(conv_handler.fallbacks)
            print(f"  ✅ ConversationHandler found: {entry_points} entry points, {states} states, {fallbacks} fallbacks")
        
        print("\n🎉 All basic functionality tests passed!")
        print("🎯 The simplified bot is ready for deployment")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_basic_functionality()
    sys.exit(0 if success else 1)