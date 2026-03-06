set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

unifi_dir := justfile_dir() + '/scripts/unifi'

default: 
    just -l unifi

[doc('Enable blocking of DNS over HTTPS')]
block-doh:
    just log info "Running stage..." "stage" "$0"
    op inject -i {{ unifi_dir }}/dns_over_https_block.conf | ssh root@192.168.1.1 'cat > /var/run/dnsmasq.dhcp.conf.d/custom.conf'
    gum confirm "Restart dnsmasq?" --default="Yes" && \
        ssh root@192.168.1.1 'killall dnsmasq'
    

