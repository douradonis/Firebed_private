#!/usr/bin/env python3
"""
Simple script to stop all ports 5000 and above
"""
import psutil
import os
import signal
import sys

def stop_ports_from_5000():
    """Stop all processes using ports 5000 and above"""
    stopped = 0
    
    try:
        print("🔧 Σταμάτημα θυρών από 5000 και πάνω...")
        
        for conn in psutil.net_connections(kind='inet'):
            if (conn.status == psutil.CONN_LISTEN and 
                conn.laddr and 
                conn.laddr.port >= 5000 and 
                conn.pid):
                
                try:
                    proc = psutil.Process(conn.pid)
                    print(f"Σταματά: PID {conn.pid} - {proc.name()} στη θύρα {conn.laddr.port}")
                    
                    # Try graceful termination first
                    proc.terminate()
                    
                    # Wait a bit, then force kill if needed
                    try:
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    
                    stopped += 1
                    
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    print(f"Δεν μπόρεσα να σταματήσω PID {conn.pid}: {e}")
                    continue
        
        print(f"✅ Σταμάτησαν {stopped} διεργασίες")
        return stopped
        
    except Exception as e:
        print(f"❌ Σφάλμα: {e}")
        return 0

if __name__ == "__main__":
    stop_ports_from_5000()
from typing import List, Dict


def get_processes_5000_plus() -> List[Dict]:
    """Βρίσκει διεργασίες που χρησιμοποιούν θύρες >= 5000"""
    processes = []
    
    try:
        # Χρήση lsof
        result = subprocess.run(['lsof', '-i', '-P', '-n'], 
                              capture_output=True, text=True, check=False)
        
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            for line in lines[1:]:  # Skip header
                if line.strip() and 'LISTEN' in line:
                    parts = line.split()
                    if len(parts) >= 9:
                        try:
                            pid = int(parts[1])
                            address = parts[8]
                            
                            if ':' in address:
                                port = address.split(':')[-1]
                                port_num = int(port)
                                
                                # Μόνο θύρες >= 5000
                                if port_num >= 5000:
                                    processes.append({
                                        'pid': pid,
                                        'port': port_num,
                                        'command': parts[0],
                                        'address': address
                                    })
                        except (ValueError, IndexError):
                            continue
        else:
            # Εναλλακτικά με netstat
            result = subprocess.run(['netstat', '-tlnp'], 
                                  capture_output=True, text=True, check=False)
            
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'LISTEN' in line:
                        parts = line.split()
                        if len(parts) >= 7:
                            try:
                                address = parts[3]
                                pid_program = parts[6]
                                
                                if ':' in address and '/' in pid_program:
                                    port = int(address.split(':')[-1])
                                    pid = int(pid_program.split('/')[0])
                                    
                                    if port >= 5000:
                                        processes.append({
                                            'pid': pid,
                                            'port': port,
                                            'command': pid_program.split('/', 1)[1],
                                            'address': address
                                        })
                            except (ValueError, IndexError):
                                continue
    
    except Exception as e:
        print(f"❌ Σφάλμα: {e}")
    
    return processes


def kill_process(pid: int) -> bool:
    """Σκοτώνει μια διεργασία"""
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"🛑 Σταμάτησε διεργασία {pid}")
        return True
    except ProcessLookupError:
        print(f"⚠️  Διεργασία {pid} δεν υπάρχει πια")
        return False
    except PermissionError:
        print(f"❌ Δεν έχετε δικαίωμα να σκοτώσετε τη διεργασία {pid}")
        return False
    except Exception as e:
        print(f"❌ Σφάλμα: {e}")
        return False


def main():
    print("🔧 Σταματά όλες τις θύρες από 5000 και πάνω")
    print("=" * 50)
    
    # Βρες διεργασίες
    processes = get_processes_5000_plus()
    
    if not processes:
        print("ℹ️  Δεν βρέθηκαν διεργασίες σε θύρες >= 5000")
        return
    
    print(f"🎯 Βρέθηκαν {len(processes)} διεργασίες:")
    print()
    
    # Εμφάνισε λίστα
    for proc in sorted(processes, key=lambda x: x['port']):
        print(f"   PID: {proc['pid']:<6} Port: {proc['port']:<6} Command: {proc['command']:<15} Address: {proc['address']}")
    
    print()
    response = input("Θέλετε να σταματήσουν όλες αυτές οι διεργασίες; (y/N): ")
    
    if response.lower() != 'y':
        print("🚫 Ακύρωση")
        return
    
    # Σκότωσε διεργασίες
    stopped_count = 0
    for proc in processes:
        if kill_process(proc['pid']):
            stopped_count += 1
    
    print(f"\n✅ Σταμάτησαν {stopped_count}/{len(processes)} διεργασίες")
    
    # Περίμενε και έλεγξε ξανά
    if stopped_count > 0:
        print("\n⏳ Περιμένω 2 δευτερόλεπτα...")
        import time
        time.sleep(2)
        
        remaining = get_processes_5000_plus()
        if remaining:
            print(f"⚠️  Εξακολουθούν να τρέχουν {len(remaining)} διεργασίες")
        else:
            print("✅ Όλες οι διεργασίες σταμάτησαν επιτυχώς")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🚫 Διακοπή από χρήστη")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Σφάλμα: {e}")
        sys.exit(1)