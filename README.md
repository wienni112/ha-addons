#############################################
# MediaMTX main configuration
#############################################

logLevel: info

# Listen on all interfaces
rtspAddress: :8554
hlsAddress: :8888
webrtcAddress: :8889

# WebRTC low latency
webrtcAllowOrigin: "*"

#############################################
# Optional authentication (uncomment if needed)
#############################################

# authMethod: internal
# authInternalUsers:
#   - user: viewer
#     pass: changeme
#     permissions:
#       - action: read

#############################################
# Global defaults
#############################################

readTimeout: 10s
writeTimeout: 10s
writeQueueSize: 512

#############################################
# Streams / Paths
#############################################

paths:

  #################################################
  # IP Cameras (RTSP Ingest)
  #################################################

  cam_einfahrt:
    source: rtsp://USER:PASS@172.22.15.10:554/STREAM
    sourceProtocol: tcp
    runOnReady: echo "Camera Einfahrt connected"

  cam_garten:
    source: rtsp://USER:PASS@172.22.15.11:554/STREAM
    sourceProtocol: tcp

  #################################################
  # IPTV via HLS (Provider / xTeVe / Playlist)
  #################################################

  rtl:
    source: https://iptv-provider.example/rtl.m3u8

  zdf:
    source: https://iptv-provider.example/zdf.m3u8

  #################################################
  # Multicast IPTV (SAT>IP / Telekom / etc.)
  #################################################

  ard_multicast:
    source: udp://239.0.0.1:10000

  zdf_multicast:
    source: udp://239.0.0.2:10000

#############################################
# Example URLs after setup
#############################################

# RTSP:
# rtsp://HA_IP:8554/cam_einfahrt
# rtsp://HA_IP:8554/rtl

# HLS (Browser / Smart TV):
# http://HA_IP:8888/cam_einfahrt
# http://HA_IP:8888/zdf

# WebRTC (Ultra low latency):
# http://HA_IP:8889
