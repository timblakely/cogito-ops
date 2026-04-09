set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

unifi_dir := justfile_dir() + '/scripts/unifi'

default: 
    just -l unifi

[doc('Install unifi-common for on-boot scripting')]
install-unifi-common:
    just log info "Installing unifi-common to UDM..." "stage" "$0"
    ssh root@192.168.1.1 'curl -fsL "https://raw.githubusercontent.com/unifi-utilities/unifi-common/HEAD/remote_install.sh" | /bin/bash'

[doc('Enable blocking of DNS over HTTPS')]
block-doh:
    just log info "Running stage..." "stage" "$0"
    ssh root@192.168.1.1 '[ -f /etc/systemd/system/udm-boot.service ]' || just unifi install-unifi-common
    op inject -i {{ unifi_dir }}/dns_over_https_block.conf | ssh root@192.168.1.1 'cat > /var/run/dnsmasq.dhcp.conf.d/custom.conf'
    op inject -i {{ unifi_dir }}/dns_over_https_block.conf | ssh root@192.168.1.1 'mkdir -p /data/on_boot.d && cat > /data/on_boot.d/99-dnsmasq-custom-config.conf'
    cat {{ unifi_dir }}/99-dnsmasq-custom.sh | ssh root@192.168.1.1 'cat > /data/on_boot.d/99-dnsmasq-custom.sh && chmod +x /data/on_boot.d/99-dnsmasq-custom.sh'
    gum confirm "Restart dnsmasq?" --default="Yes" && \
        ssh root@192.168.1.1 'killall dnsmasq'

