# Dump what FUN_004f4130 actually sees in memory when it parses a .chr.
# Game must already be running, then:
#
#   pid=$(for p in /proc/[0-9]*; do
#           grep -ql -i 'XANADU.exe' "$p/maps" 2>/dev/null && echo ${p##*/}
#         done | head -1)
#   sudo gdb -p "$pid" -x scripts/chr_trace.gdb

set pagination off
set print elements 0
set logging file /tmp/chr_trace.log
set logging overwrite on
set logging enabled on

# Break AFTER the prologue, where ESI = param_1 (the file struct).
# Prologue ends at 004f415b (MOV ESI, dword ptr [EBP+0x8]); ESI valid
# starting at 004f415e.
break *0x004f415e
commands
  silent
  printf "\n=== FUN_004f4130 hit ===\n"
  printf "esi (file struct ptr) = 0x%x\n", $esi
  printf "  [esi+0]  FILE*    = 0x%x\n", *(int*)($esi+0)
  printf "  [esi+4]  buffer   = 0x%x\n", *(int*)($esi+4)
  printf "  [esi+8]  position = %d\n", *(int*)($esi+8)
  printf "  [esi+c]  size     = %d\n", *(int*)($esi+12)
  printf "  caller (return addr) = 0x%x\n", *(int*)($ebp+4)
  set $bufbase = *(int*)($esi+4)
  set $pos = *(int*)($esi+8)
  if $bufbase != 0
    set $src = $bufbase + $pos
    printf "  next-read source = 0x%x  (buffer + position)\n", $src
    printf "\n--- next 256 bytes the parser will consume ---\n"
    x/256xb $src
  else
    printf "  (file is read via FILE*, not buffered — can't dump from here)\n"
  end
  continue
end

continue
