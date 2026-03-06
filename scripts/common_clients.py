#!/usr/bin/env python3
"""
公共HTTP客户端模块
提供统一的HTTP/HTTPS mTLS客户端实现，可在多个脚本中复用

包含的类:
- SimpleSettings: 配置管理类
- SimpleHttpsMtlsClient: HTTPS mTLS客户端
- SimpleBaseClient: 统一的HTTP/HTTPS客户端基类
"""
import os
import ssl
import stat
import tempfile
import asyncio
import logging
from typing import Any, Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# HTTP客户端依赖
import httpx
import aiohttp
from typing import cast
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, NoEncryption, pkcs12
)


# ============================================================================
# 配置类
# ============================================================================
class SimpleSettings:
    """简化的配置类，从环境变量读取"""
    def __init__(self):
        # 金融查数接口配置
        self.fin_sql_container_host = os.getenv("FIN_SQL_CONTAINER_HOST", "http://cbas-babel-frontend-prod:10399")
        self.environment = os.getenv("THS_TIER", "dev")
        self.ssl_cert_file = os.getenv("SSL_CERT_FILE", "")
        self.ssl_cert_password = os.getenv("SSL_CERT_PASSWORD", "")


settings = SimpleSettings()


# ============================================================================
# HTTPS mTLS客户端
# ============================================================================
class SimpleHttpsMtlsClient:
    """简化的HTTPS mTLS客户端 - 支持P12和PEM证书格式"""

    def __init__(self, cert_path: str, cert_password: str, base_url: str, timeout: int = 300):
        self.cert_path = cert_path
        self.cert_password = cert_password
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None
        self.ssl_context = None
        self.temp_cert_file = None

        # 初始化 SSL 上下文
        self._init_ssl_context()

    def _init_ssl_context(self):
        """初始化SSL上下文 - 支持P12和PEM证书格式"""
        cert_path_obj = Path(self.cert_path)

        # 检查证书文件是否存在
        if not cert_path_obj.exists():
            raise FileNotFoundError(f"证书文件不存在: {self.cert_path}")

        # 处理 P12 证书
        if cert_path_obj.suffix.lower() in ['.p12', '.pfx']:
            try:
                # 读取 P12 文件
                with open(self.cert_path, 'rb') as f:
                    p12_data = f.read()

                # 解析 P12 证书
                private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
                    p12_data,
                    self.cert_password.encode()
                )

                if private_key is None or certificate is None:
                    raise ValueError(f"P12 file at {self.cert_path} does not contain a valid private key and certificate")

                # 转换为 PEM 格式
                cert_pem = certificate.public_bytes(Encoding.PEM)
                key_pem = private_key.private_bytes(
                    encoding=Encoding.PEM,
                    format=PrivateFormat.PKCS8,
                    encryption_algorithm=NoEncryption()
                )

                # 创建临时文件保存合并后的 PEM
                combined_fd, combined_path = tempfile.mkstemp(suffix='.pem', prefix='combined_')
                os.write(combined_fd, key_pem)
                os.write(combined_fd, cert_pem)

                # 如果有中间证书，也添加到文件中
                if additional_certs:
                    for cert in additional_certs:
                        os.write(combined_fd, cert.public_bytes(Encoding.PEM))

                os.close(combined_fd)
                os.chmod(combined_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
                self.temp_cert_file = combined_path

            except Exception as e:
                # Clean up temp file on failure
                if 'combined_path' in locals() and os.path.exists(combined_path):
                    try:
                        os.remove(combined_path)
                    except OSError:
                        pass
                raise RuntimeError(f"转换 P12 证书失败: {str(e)}")

        elif cert_path_obj.suffix.lower() in ['.pem', '.crt']:
            # PEM 格式证书直接使用
            self.temp_cert_file = str(cert_path_obj)
        else:
            raise ValueError(f"不支持的证书格式: {cert_path_obj.suffix}")

        # 创建 SSL 上下文
        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

        # 降低安全级别以支持旧证书
        try:
            self.ssl_context.set_ciphers('DEFAULT@SECLEVEL=0')
        except Exception as e:
            logger.warning("Failed to set cipher DEFAULT@SECLEVEL=0: %s, trying DEFAULT", e)
            try:
                self.ssl_context.set_ciphers('DEFAULT')
            except Exception as e2:
                logger.warning("Failed to set cipher DEFAULT: %s", e2)

        # 加载客户端证书
        try:
            self.ssl_context.load_cert_chain(certfile=self.temp_cert_file)
        except Exception as e:
            raise RuntimeError(f"加载证书失败: {str(e)}")

        # 不验证服务器证书（企业自签名）
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    async def _ensure_session(self):
        """确保会话已创建"""
        if self.session is None or self.session.closed:
            # 创建 TCP 连接器
            connector = aiohttp.TCPConnector(
                ssl=self.ssl_context,
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300
            )

            # 创建 session
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            )

    async def close(self):
        """关闭会话"""
        if self.session and not self.session.closed:
            await self.session.close()
            await asyncio.sleep(0.250)  # 等待底层连接关闭

        # 清理临时证书文件
        if self.temp_cert_file and self.cert_path.lower().endswith(('.p12', '.pfx')):
            if os.path.exists(self.temp_cert_file):
                try:
                    os.remove(self.temp_cert_file)
                except OSError:
                    pass

        self.session = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def post(self, endpoint: str, json: Optional[Dict] = None,
                   data: Any = None, headers: Optional[Dict] = None) -> Dict:
        """发送POST请求"""
        await self._ensure_session()
        url = f"{self.base_url}{endpoint}"

        async with self.session.post(url, json=json, data=data, headers=headers,
                                      ssl=self.ssl_context or False) as response:
            status = response.status
            headers_dict = dict(response.headers)

            try:
                json_data = await response.json()
                return {'status': status, 'headers': headers_dict, 'json': json_data}
            except Exception:
                body = await response.text()
                return {'status': status, 'headers': headers_dict, 'body': body}


# ============================================================================
# BaseClient - 统一HTTP/HTTPS客户端
# ============================================================================
class SimpleBaseClient:
    """简化的HTTP/HTTPS客户端 - 根据环境自动选择HTTP或HTTPS mTLS"""

    def __init__(self, base_url: str, timeout: float = 300.0, headers: Optional[Dict[str, str]] = None):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.default_headers = headers or {}
        self.environment = settings.environment
        self._client: Optional[httpx.AsyncClient] = None
        self._https_client: Optional[SimpleHttpsMtlsClient] = None

    async def _get_client(self):
        """获取或创建客户端"""
        if self.environment == "dev":
            if self._https_client is None:
                self._https_client = SimpleHttpsMtlsClient(
                    cert_path=settings.ssl_cert_file,
                    cert_password=settings.ssl_cert_password,
                    base_url=self.base_url,
                    timeout=int(self.timeout)
                )
            return self._https_client
        else:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    headers=self.default_headers,
                    timeout=self.timeout
                )
            return self._client

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._https_client:
            await self._https_client.close()
            self._https_client = None

    async def post(self, endpoint: str, json: Optional[Dict[str, Any]] = None,
                   files: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Dict:
        """发送POST请求"""
        request_headers = {**self.default_headers}
        if headers:
            request_headers.update(headers)

        client = await self._get_client()

        if self.environment == "dev":
            # dev环境使用HTTPS mTLS
            mtls_client = cast(SimpleHttpsMtlsClient, client)

            # 如果有files参数，需要转换为aiohttp的FormData格式
            data = None
            if files:
                form_data = aiohttp.FormData()
                for field_name, field_value in files.items():
                    if isinstance(field_value, tuple):
                        if field_value[0] is None:
                            form_data.add_field(field_name, str(field_value[1]))
                        else:
                            form_data.add_field(
                                field_name,
                                field_value[1],
                                filename=field_value[0],
                                content_type=field_value[2] if len(field_value) > 2 else None
                            )
                    else:
                        form_data.add_field(field_name, str(field_value))
                data = form_data

            return await mtls_client.post(endpoint, json=json, data=data, headers=request_headers)
        else:
            # prod环境使用HTTP
            url = f"{self.base_url}{endpoint}"
            http_client = cast(httpx.AsyncClient, client)
            response = await http_client.post(url, json=json, files=files, headers=request_headers)

            result: Dict[str, Any] = {
                'status': response.status_code,
                'headers': dict(response.headers)
            }
            try:
                result['json'] = response.json()
            except Exception:
                result['body'] = response.text
            return result
