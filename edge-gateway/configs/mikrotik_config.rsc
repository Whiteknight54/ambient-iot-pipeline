# =============================================================
# mikrotik_config.rsc
# Edge Gateway Network Configuration - Ambient IoT Pipeline
# RouterOS v7.x | Author: Whiteknight54
#
# Purpose: Isolate the Ambient IoT perception/edge layer on a
# dedicated VLAN and enforce a default-deny firewall so that
# only authenticated MQTT/TLS traffic to AWS IoT Core (eu-west-2)
# can leave the segment.
#
# Control mapping:
#   - Segmentation & least privilege : NIST SP 800-160 (trustworthy
#     secure design); ISO/IEC 27001:2022 A.8.22 (network segregation)
#   - Default-deny egress            : ISO/IEC 27001:2022 A.8.20/A.8.21
#   - Zero-Trust posture             : no implicit trust between VLANs
# =============================================================

# --- 1. Bridge with VLAN filtering -----------------------------
/interface bridge
add name=br-core vlan-filtering=yes comment="Core bridge, VLAN-aware"

# --- 2. VLAN interfaces ----------------------------------------
# VLAN 10 = Management (admin access only)
# VLAN 20 = Ambient IoT segment (edge gateway + MQTT publisher)
/interface vlan
add interface=br-core vlan-id=10 name=vlan10-mgmt comment="Management VLAN"
add interface=br-core vlan-id=20 name=vlan20-aiot comment="Ambient IoT VLAN (isolated)"

# --- 3. Interface lists ----------------------------------------
/interface list
add name=WAN comment="Upstream / Internet"
add name=MGMT comment="Trusted management"
add name=AIOT comment="Untrusted IoT segment"
/interface list member
add interface=ether1 list=WAN
add interface=vlan10-mgmt list=MGMT
add interface=vlan20-aiot list=AIOT

# --- 4. Bridge ports and VLAN table ----------------------------
# ether2 = management access port; ether3 = IoT hub access port
/interface bridge port
add bridge=br-core interface=ether2 pvid=10 comment="Access: mgmt"
add bridge=br-core interface=ether3 pvid=20 comment="Access: IoT hub"
/interface bridge vlan
add bridge=br-core tagged=br-core untagged=ether2 vlan-ids=10
add bridge=br-core tagged=br-core untagged=ether3 vlan-ids=20

# --- 5. IP addressing ------------------------------------------
/ip address
add address=192.168.10.1/24 interface=vlan10-mgmt comment="Mgmt gateway"
add address=192.168.20.1/24 interface=vlan20-aiot comment="IoT gateway"

# --- 6. DHCP for the IoT segment -------------------------------
/ip pool
add name=pool-aiot ranges=192.168.20.10-192.168.20.100
/ip dhcp-server
add name=dhcp-aiot interface=vlan20-aiot address-pool=pool-aiot
/ip dhcp-server network
add address=192.168.20.0/24 gateway=192.168.20.1 dns-server=192.168.20.1

# --- 7. Egress allow-list: AWS IoT Core endpoint ---------------
# RouterOS v7 resolves FQDN entries dynamically, pinning egress
# to the account-specific ATS endpoint only.
/ip firewall address-list
add list=aws-iot-core address=a2f7tdbrmlxjya-ats.iot.eu-west-2.amazonaws.com \
    comment="AWS IoT Core ATS endpoint, eu-west-2"

# --- 8. Firewall: INPUT chain (traffic to the router) ----------
/ip firewall filter
add chain=input action=accept connection-state=established,related \
    comment="Allow established/related"
add chain=input action=accept in-interface-list=MGMT protocol=tcp \
    dst-port=22,8291 comment="SSH/WinBox from mgmt VLAN only"
add chain=input action=accept in-interface-list=AIOT protocol=udp \
    dst-port=53 comment="DNS for IoT segment (endpoint resolution)"
add chain=input action=drop comment="Default deny: input"

# --- 9. Firewall: FORWARD chain (inter-segment + egress) -------
add chain=forward action=accept connection-state=established,related \
    comment="Allow established/related"
add chain=forward action=accept in-interface-list=AIOT \
    out-interface-list=WAN protocol=tcp dst-port=8883 \
    dst-address-list=aws-iot-core \
    comment="Permit MQTT/TLS (8883) to AWS IoT Core ONLY"
add chain=forward action=accept in-interface-list=AIOT \
    out-interface-list=WAN protocol=udp dst-port=123 \
    comment="NTP (TLS cert validation requires accurate time)"
add chain=forward action=drop in-interface-list=AIOT \
    out-interface-list=MGMT \
    comment="Block IoT -> Management (lateral movement)"
add chain=forward action=drop in-interface-list=MGMT \
    out-interface-list=AIOT \
    comment="Block Management -> IoT (Zero-Trust symmetry)"
add chain=forward action=drop \
    comment="Default deny: forward"

# --- 10. NAT for permitted egress ------------------------------
/ip firewall nat
add chain=srcnat action=masquerade out-interface-list=WAN \
    comment="Masquerade permitted egress"

# --- 11. Service hardening -------------------------------------
/ip service
set telnet disabled=yes
set ftp disabled=yes
set www disabled=yes
set api disabled=yes
set api-ssl disabled=yes
set ssh address=192.168.10.0/24
set winbox address=192.168.10.0/24

/ip dns
set allow-remote-requests=yes servers=1.1.1.1,8.8.8.8

# --- End of configuration --------------------------------------