import sys, subprocess

def restart():
    """Restarts the current program, with file objects and descriptors cleanup"""
    try:
        subprocess.Popen([sys.executable, "Main_File_NoUI.py"])
    except Exception as e:
        print(f"Error restarting the program: {e}")

restart()