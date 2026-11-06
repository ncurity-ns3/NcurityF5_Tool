# 정상 접속 시도 및 TS 쿠키 확인
curl -vk --resolve curl.ncurity.com:80:192.168.41.91 "http://curl.ncurity.com" -c cookie.txt

# 정상 재 접속 ( 통과 확인 )
curl -vk --resolve curl.ncurity.com:80:192.168.41.91 "http://curl.ncurity.com" -b cookie.txt

# 쿠키 값 변조 후 재요청 ( 차단 확인 )
curl -vk --resolve curl.ncurity.com:80:192.168.41.91 "http://curl.ncurity.com" -b "TS01234567=hacked"