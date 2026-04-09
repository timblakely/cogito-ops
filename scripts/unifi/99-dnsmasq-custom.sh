#!/bin/sh
if [ ! -f /var/run/dnsmasq.dhcp.conf.d/custom.conf ]; then
  cp /data/on_boot.d/99-dnsmasq-custom-config.conf /var/run/dnsmasq.dhcp.conf.d/custom.conf
  /etc/init.d/dnsmasq force-reload
  pkill dnsmasq
fi
