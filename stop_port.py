#!/usr/bin/env python3
"""
Stop Port Script - Σταματά όλες τις θύρες που χρησιμοποιούνται
Χρήση: python stop_port.py [--port PORT] [--all] [--force] [--from 5000]
"""

import subprocess
import sys
import argparse
import os
import signal
import time
import psutil
from typing import List, Dict, Optional


def get_processes_using_ports() -> List[Dict]:
    """Βρίσκει όλες τις διεργασίες που χρησιμοποιούν θύρες με psutil"""
    try:
        processes = []
        
        # Χρήση psutil για αξιόπιστη ανίχνευση
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == psutil.CONN_LISTEN and conn.laddr:
                try:
                    if conn.pid:
                        proc = psutil.Process(conn.pid)
                        processes.append({
                            'pid': conn.pid,
                            'port': conn.laddr.port,
                            'command': proc.name(),
                            'address': f"{conn.laddr.ip}:{conn.laddr.port}",
                            'user': proc.username() if hasattr(proc, 'username') else 'unknown'
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        
        return processes
    
    except Exception as e:
        print(f"❌ Σφάλμα κατά την αναζήτηση διεργασιών: {e}")
        # Fallback to lsof if psutil fails
        return get_processes_using_lsof_fallback()


def get_processes_using_lsof_fallback() -> List[Dict]:
    """Εναλλακτικός τρόπος με lsof (fallback)"""
    try:
        result = subprocess.run(['lsof', '-i', '-P', '-n'], 
                              capture_output=True, text=True, check=False, timeout=10)
        
        if result.returncode != 0:
            return []
        
        lines = result.stdout.split('\n')
        processes = []
        
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
                            processes.append({
                                'pid': pid,
                                'port': port_num,
                                'command': parts[0],
                                'address': address,
                                'user': parts[2] if len(parts) > 2 else 'unknown'
                            })
                    except (ValueError, IndexError):
                        continue
        
        return processes
    
    except Exception:
        return []


def stop_ports_from_5000():
    """Σταματά όλες τις θύρες από 5000 και πάνω - κύρια συνάρτηση"""
    return stop_ports_from_range(5000, force=True)


def stop_ports_from_range(min_port: int, force: bool = False) -> int:
    """Σταματά όλες τις διεργασίες που χρησιμοποιούν θύρες από min_port και πάνω"""
    processes = get_processes_using_ports()
    
    if not processes:
        print("ℹ️  Δεν βρέθηκαν διεργασίες που χρησιμοποιούν θύρες")
        return 0
    
    # Φίλτρο για θύρες >= min_port
    filtered_processes = [p for p in processes if p['port'] >= min_port]
    
    if not filtered_processes:
        print(f"ℹ️  Δεν βρέθηκαν διεργασίες σε θύρες >= {min_port}")
        return 0
    
    print(f"🎯 Βρέθηκαν {len(filtered_processes)} διεργασίες σε θύρες >= {min_port}:")
    
    stopped_count = 0
    for proc in filtered_processes:
        print(f"   PID: {proc['pid']}, Port: {proc['port']}, Command: {proc['command']}")
        if kill_process(proc['pid'], force):
            stopped_count += 1
    
    return stopped_count


def get_processes_using_netstat() -> List[Dict]:
    """Εναλλακτικός τρόπος με netstat"""
    try:
        result = subprocess.run(['netstat', '-tlnp'], 
                              capture_output=True, text=True, check=False)
        
        if result.returncode != 0:
            print("❌ Ούτε netstat είναι διαθέσιμο")
            return []
        
        lines = result.stdout.split('\n')
        processes = []
        
        for line in lines:
            if 'LISTEN' in line:
                parts = line.split()
                if len(parts) >= 7:
                    try:
                        address = parts[3]
                        pid_program = parts[6]
                        
                        if ':' in address:
                            port = address.split(':')[-1]
                            port_num = int(port)
                            
                            # Εξαγωγή PID από το format "PID/program"
                            if '/' in pid_program:
                                pid = int(pid_program.split('/')[0])
                                program = pid_program.split('/', 1)[1]
                            else:
                                continue
                            
                            processes.append({
                                'pid': pid,
                                'port': port_num,
                                'command': program,
                                'address': address,
                                'user': 'unknown'
                            })
                    except (ValueError, IndexError):
                        continue
        
        return processes
    
    except Exception as e:
        print(f"❌ Σφάλμα με netstat: {e}")
        return []


def kill_process(pid: int, force: bool = False) -> bool:
    """Σκοτώνει μια διεργασία"""
    try:
        if force:
            os.kill(pid, signal.SIGKILL)
            print(f"🔥 Δυναμική διακοπή διεργασίας {pid}")
        else:
            os.kill(pid, signal.SIGTERM)
            print(f"🛑 Ευγενική διακοπή διεργασίας {pid}")
        return True
    except ProcessLookupError:
        print(f"⚠️  Διεργασία {pid} δεν υπάρχει πια")
        return False
    except PermissionError:
        print(f"❌ Δεν έχετε δικαίωμα να σκοτώσετε τη διεργασία {pid}")
        return False
    except Exception as e:
        print(f"❌ Σφάλμα κατά τη διακοπή διεργασίας {pid}: {e}")
        return False


def stop_processes_on_port(port: int, force: bool = False) -> int:
    """Σταματά όλες τις διεργασίες σε μια συγκεκριμένη θύρα"""
    processes = get_processes_using_ports()
    port_processes = [p for p in processes if p['port'] == port]
    
    if not port_processes:
        print(f"ℹ️  Δεν βρέθηκαν διεργασίες στη θύρα {port}")
        return 0
    
    print(f"🎯 Βρέθηκαν {len(port_processes)} διεργασίες στη θύρα {port}:")
    
    stopped_count = 0
    for proc in port_processes:
        print(f"   PID: {proc['pid']}, Command: {proc['command']}, Address: {proc['address']}")
        if kill_process(proc['pid'], force):
            stopped_count += 1
    
    return stopped_count


def stop_all_listening_processes(force: bool = False, exclude_system: bool = True) -> int:
    """Σταματά όλες τις διεργασίες που ακούν σε θύρες"""
    processes = get_processes_using_ports()
    
    if not processes:
        print("ℹ️  Δεν βρέθηκαν διεργασίες που χρησιμοποιούν θύρες")
        return 0
    
    # Εξαίρεση συστηματικών θυρών (< 1024) αν ζητηθεί
    if exclude_system:
        processes = [p for p in processes if p['port'] >= 1024]
    
    print(f"🎯 Βρέθηκαν {len(processes)} διεργασίες που χρησιμοποιούν θύρες:")
    
    stopped_count = 0
    for proc in processes:
        print(f"   PID: {proc['pid']}, Port: {proc['port']}, Command: {proc['command']}")
        if kill_process(proc['pid'], force):
            stopped_count += 1
    
    return stopped_count


def stop_ports_from_range(min_port: int, force: bool = False) -> int:
    """Σταματά όλες τις διεργασίες που χρησιμοποιούν θύρες από min_port και πάνω"""
    processes = get_processes_using_ports()
    
    if not processes:
        print("ℹ️  Δεν βρέθηκαν διεργασίες που χρησιμοποιούν θύρες")
        return 0
    
    # Φίλτρο για θύρες >= min_port
    filtered_processes = [p for p in processes if p['port'] >= min_port]
    
    if not filtered_processes:
        print(f"ℹ️  Δεν βρέθηκαν διεργασίες σε θύρες >= {min_port}")
        return 0
    
    print(f"🎯 Βρέθηκαν {len(filtered_processes)} διεργασίες σε θύρες >= {min_port}:")
    
    stopped_count = 0
    for proc in filtered_processes:
        print(f"   PID: {proc['pid']}, Port: {proc['port']}, Command: {proc['command']}")
        if kill_process(proc['pid'], force):
            stopped_count += 1
    
    return stopped_count


def list_listening_processes():
    """Εμφανίζει όλες τις διεργασίες που ακούν σε θύρες"""
    processes = get_processes_using_ports()
    
    if not processes:
        print("ℹ️  Δεν βρέθηκαν διεργασίες που χρησιμοποιούν θύρες")
        return
    
    print(f"\n📋 Βρέθηκαν {len(processes)} διεργασίες που χρησιμοποιούν θύρες:\n")
    print(f"{'PID':<8} {'Port':<6} {'Address':<20} {'User':<10} {'Command'}")
    print("-" * 60)
    
    for proc in sorted(processes, key=lambda x: x['port']):
        print(f"{proc['pid']:<8} {proc['port']:<6} {proc['address']:<20} {proc['user']:<10} {proc['command']}")


def main():
    parser = argparse.ArgumentParser(
        description="🔧 Σταματά διεργασίες που χρησιμοποιούν θύρες",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Παραδείγματα χρήσης:
  python stop_port.py --list                     # Εμφάνιση όλων των θυρών
  python stop_port.py --port 5000               # Σταματά θύρα 5000
  python stop_port.py --dev                     # Σταματά θύρες 5000+ (development)
  python stop_port.py --from 8000               # Σταματά θύρες από 8000 και πάνω
  python stop_port.py --port 8080 --force       # Δυναμική διακοπή θύρας 8080
  python stop_port.py --all                     # Σταματά όλες τις θύρες (>= 1024)
  python stop_port.py --all --system --force    # Σταματά ΟΛΑ (επικίνδυνο!)
        """
    )
    
    parser.add_argument('--port', '-p', type=int, 
                       help='Θύρα για διακοπή')
    parser.add_argument('--all', '-a', action='store_true',
                       help='Σταματά όλες τις διεργασίες που χρησιμοποιούν θύρες')
    parser.add_argument('--from', '-r', type=int, dest='from_port',
                       help='Σταματά όλες τις θύρες από αυτή την τιμή και πάνω')
    parser.add_argument('--dev', action='store_true',
                       help='Σταματά όλες τις development θύρες (5000+) - shortcut για --from 5000')
    parser.add_argument('--force', '-f', action='store_true',
                       help='Δυναμική διακοπή (SIGKILL αντί για SIGTERM)')
    parser.add_argument('--system', '-s', action='store_true',
                       help='Συμπεριλαμβάνει συστηματικές θύρες (<1024) - ΕΠΙΚΙΝΔΥΝΟ!')
    parser.add_argument('--list', '-l', action='store_true',
                       help='Εμφάνιση όλων των διεργασιών που χρησιμοποιούν θύρες')
    
    args = parser.parse_args()
    
    # Έλεγχος αν δεν δόθηκε καμία επιλογή
    if not any([args.port, args.all, args.list, args.from_port, args.dev]):
        print("❌ Παρακαλώ καθορίστε --port, --all, --dev, --from ή --list")
        parser.print_help()
        sys.exit(1)
    
    print("🔧 Stop Port Script - Διαχείριση θυρών")
    print("=" * 50)
    
    if args.list:
        list_listening_processes()
        return
    
    if args.system and not args.force:
        print("⚠️  ΠΡΟΕΙΔΟΠΟΙΗΣΗ: Χρήση --system χωρίς --force μπορεί να προκαλέσει προβλήματα!")
        response = input("Συνέχεια; (y/N): ")
        if response.lower() != 'y':
            print("🚫 Ακύρωση")
            sys.exit(0)
    
    try:
        stopped_count = 0
        
        if args.port:
            print(f"\n🎯 Στόχος: Θύρα {args.port}")
            stopped_count = stop_processes_on_port(args.port, args.force)
        
        elif args.dev:
            print(f"\n🎯 Στόχος: Development θύρες (5000+)")
            stopped_count = stop_ports_from_range(5000, args.force)
        
        elif args.from_port:
            print(f"\n🎯 Στόχος: Θύρες από {args.from_port} και πάνω")
            stopped_count = stop_ports_from_range(args.from_port, args.force)
        
        elif args.all:
            print(f"\n🎯 Στόχος: Όλες οι θύρες {'(συμπεριλαμβάνοντας συστηματικές)' if args.system else '(εκτός συστηματικών)'}")
            stopped_count = stop_all_listening_processes(args.force, not args.system)
        
        print(f"\n✅ Ολοκληρώθηκε! Σταμάτησαν {stopped_count} διεργασίες")
        
        # Περίμενε λίγο και εμφάνισε την τρέχουσα κατάσταση
        if stopped_count > 0:
            print("\n⏳ Περιμένω 2 δευτερόλεπτα για επιβεβαίωση...")
            time.sleep(2)
            print("\n📋 Τρέχουσα κατάσταση:")
            list_listening_processes()
    
    except KeyboardInterrupt:
        print("\n🚫 Διακοπή από χρήστη")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Απροσδόκητο σφάλμα: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()