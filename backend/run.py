#!/usr/bin/env python3
"""
NOVA Backend Runner

Simple script to start the NOVA backend server.
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=9360,
        reload=True
    )
