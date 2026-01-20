"""
SQLite version fix for ChromaDB on older systems
This must be imported BEFORE chromadb
"""
import sys

# Check if we need the fix
try:
    import sqlite3
    if sqlite3.sqlite_version_info < (3, 35, 0):
        # Override sqlite3 with pysqlite3 (only on Linux)
        try:
            __import__('pysqlite3')
            sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
            print(f"✅ SQLite upgraded: {sys.modules['sqlite3'].sqlite_version}")
        except ImportError:
            print(f"⚠️ SQLite version {sqlite3.sqlite_version} is old. ChromaDB may not work.")
            print("   Install pysqlite3-binary on Linux to fix this.")
    else:
        print(f"✅ SQLite version {sqlite3.sqlite_version} is compatible")
except Exception as e:
    print(f"⚠️ SQLite check warning: {e}")
