-- Wireshark / tshark dissector for Homa (IP protocol 146), written from HomaModule's homa_wire.h (main, 2026-10).
-- HomaModule's own dissector/ still expects protocol 253 and the pre-2024 header layout. Install: copy to
-- ~/.local/lib/wireshark/plugins/ (or the global plugins directory). TCP-hijacked Homa (sysctl hijack_tcp=1) is not covered.
local homa = Proto("homa", "Homa")

local types = { [0x10] = "DATA", [0x11] = "GRANT", [0x12] = "RESEND", [0x13] = "RPC_UNKNOWN", [0x14] = "BUSY",
                [0x15] = "CUTOFFS", [0x16] = "FREEZE", [0x17] = "NEED_ACK", [0x18] = "ACK", [0x19] = "START_MSG" }

local f = {
  sport     = ProtoField.uint16("homa.sport", "Source port"),
  dport     = ProtoField.uint16("homa.dport", "Destination port"),
  sequence  = ProtoField.uint32("homa.sequence", "Sequence (TSO)"),
  type      = ProtoField.uint8("homa.type", "Type", base.HEX, types),
  type_name = ProtoField.string("homa.type_name", "Type name"),
  doff      = ProtoField.uint8("homa.doff", "Data offset (4-byte words, high nibble)", base.HEX),
  flags     = ProtoField.uint8("homa.flags", "Flags", base.HEX),
  urgent    = ProtoField.uint16("homa.urgent", "Urgent (0xb97d = TCP hijack)", base.HEX),
  sender_id = ProtoField.uint64("homa.sender_id", "Sender RPC id"),
  rpc_id    = ProtoField.uint64("homa.rpc_id", "RPC id (client's)"),
  from_client = ProtoField.bool("homa.from_client", "Sent by the client"),
  msg_length = ProtoField.uint32("homa.msg_length", "Message length"),
  ack_client_id = ProtoField.uint64("homa.ack.client_id", "Piggybacked ack: client id"),
  ack_server_port = ProtoField.uint16("homa.ack.server_port", "Piggybacked ack: server port"),
  cutoff_version = ProtoField.uint16("homa.cutoff_version", "Cutoff version"),
  retransmit = ProtoField.uint8("homa.retransmit", "Retransmission"),
  offset    = ProtoField.uint32("homa.offset", "Offset"),
  seg_length = ProtoField.uint32("homa.seg_length", "Segment data length"),
  priority  = ProtoField.uint8("homa.priority", "Priority"),
  length    = ProtoField.uint32("homa.length", "Length"),
  cutoff    = ProtoField.uint32("homa.cutoff", "Unscheduled cutoff"),
  num_acks  = ProtoField.uint16("homa.num_acks", "Acks"),
}
homa.fields = f

local COMMON = 28

function homa.dissector(tvb, pinfo, tree)
  if tvb:len() < COMMON then return 0 end
  pinfo.cols.protocol = "Homa"
  local t = tvb(11, 1):uint()
  local name = types[t] or string.format("0x%02x", t)
  local st = tree:add(homa, tvb(), "Homa " .. name)
  st:add(f.sport, tvb(0, 2)); st:add(f.dport, tvb(2, 2)); st:add(f.sequence, tvb(4, 4))
  st:add(f.type, tvb(11, 1)); st:add(f.type_name, name); st:add(f.doff, tvb(12, 1)); st:add(f.flags, tvb(13, 1)); st:add(f.urgent, tvb(18, 2))
  local sid = tvb(20, 8):uint64()
  st:add(f.sender_id, tvb(20, 8))
  -- client ids are even; a server sends the client's id with the low bit set
  local from_client = (sid:band(UInt64(1)) == UInt64(0))
  st:add(f.rpc_id, tvb(20, 8), sid:band(UInt64(0xFFFFFFFE, 0xFFFFFFFF))):set_generated()
  st:add(f.from_client, from_client):set_generated()
  local info = string.format("%s %d → %d id=%s", name, tvb(0, 2):uint(), tvb(2, 2):uint(), tostring(sid:band(UInt64(0xFFFFFFFE, 0xFFFFFFFF))))
  if t == 0x10 and tvb:len() >= 56 then
    st:add(f.msg_length, tvb(28, 4)); st:add(f.ack_client_id, tvb(36, 8)); st:add(f.ack_server_port, tvb(44, 2))
    st:add(f.cutoff_version, tvb(46, 2)); st:add(f.retransmit, tvb(48, 1)); st:add(f.offset, tvb(52, 4))
    st:add(f.seg_length, tvb:len() - 56):set_generated()
    info = info .. string.format(" off=%d len=%d msg=%d%s", tvb(52, 4):uint(), tvb:len() - 56, tvb(28, 4):uint(), tvb(48, 1):uint() ~= 0 and " RETRANSMIT" or "")
  elseif t == 0x11 and tvb:len() >= 33 then
    st:add(f.offset, tvb(28, 4)); st:add(f.priority, tvb(32, 1))
    info = info .. string.format(" granted=%d prio=%d", tvb(28, 4):uint(), tvb(32, 1):uint())
  elseif t == 0x12 and tvb:len() >= 36 then
    st:add(f.offset, tvb(28, 4)); st:add(f.length, tvb(32, 4))
    if tvb:len() >= 37 then st:add(f.priority, tvb(36, 1)) end
    info = info .. string.format(" off=%d len=%d", tvb(28, 4):uint(), tvb(32, 4):uint())
  elseif t == 0x15 and tvb:len() >= COMMON + 34 then
    for i = 0, 7 do st:add(f.cutoff, tvb(COMMON + 4 * i, 4)) end
    st:add(f.cutoff_version, tvb(COMMON + 32, 2))
  elseif t == 0x18 and tvb:len() >= 30 then
    st:add(f.num_acks, tvb(28, 2))
    for i = 0, math.min(tvb(28, 2):uint(), 5) - 1 do
      local o = 30 + 10 * i
      if tvb:len() >= o + 10 then st:add(f.ack_client_id, tvb(o, 8)); st:add(f.ack_server_port, tvb(o + 8, 2)) end
    end
    info = info .. string.format(" acks=%d", tvb(28, 2):uint())
  elseif t == 0x19 and tvb:len() >= 32 then
    st:add(f.msg_length, tvb(28, 4))
    info = info .. string.format(" msg=%d", tvb(28, 4):uint())
  end
  pinfo.cols.info = info
  return tvb:len()
end

DissectorTable.get("ip.proto"):add(146, homa)
