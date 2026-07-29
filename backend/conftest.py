# conftest.py — shared pytest configuration
import sys
import os

# Make sure 'backend/' is always on the Python path when running tests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
