"""第三方配置管理：校验后保存即生效，执行 JWT 不授予管理权限。"""
import asyncio
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from runtime.auth import JWTError, _verify_signed_claims
from runtime.config_store import TABLES, config_store
from runtime.configuration import validate_configuration

router = APIRouter(prefix='/internal/config/v1')

async def authorize(request):
    if request.headers.get('origin'): raise HTTPException(403, 'configuration_origin_forbidden')
    try:
        row = await asyncio.to_thread(config_store().load)
    except RuntimeError:
        raise HTTPException(503, 'configuration_unavailable') from None
    security = row['settings']['security']['value']
    secret = security.get('configurationJwtSecret')
    if not secret or secret in (security.get('runtimeJwtSecret'), security.get('observationJwtSecret')):
        raise HTTPException(503, 'configuration_auth_not_configured')
    authorization = request.headers.get('authorization', '')
    try:
        if not authorization.startswith('Bearer '): raise JWTError('missing_token')
        claims = _verify_signed_claims(authorization[7:], secret, audience='ccsdk-config',
            issuer=security.get('runtimeJwtIssuer','string-ai-center-service'),
            expected_scope='configuration.manage', required_claims=('sub',))
        if claims['exp'] - claims['iat'] > 300: raise JWTError('token_too_long')
        return claims
    except JWTError:
        raise HTTPException(401, 'configuration_auth_failed') from None

def resource_table(resource):
    if resource not in TABLES: raise HTTPException(404, 'configuration_resource_not_found')

@router.get('/{resource}')
async def list_records(resource: str, request: Request):
    await authorize(request)
    resource_table(resource)
    return await asyncio.to_thread(config_store().list, resource)

@router.get('/{resource}/{ref}')
async def get_record(resource: str, ref: str, request: Request):
    await authorize(request)
    resource_table(resource)
    try:
        return await asyncio.to_thread(config_store().get, resource, ref)
    except KeyError:
        raise HTTPException(404, 'configuration_not_found') from None

@router.put('/{resource}/{ref}')
async def save_record(resource: str, ref: str, request: Request):
    await authorize(request)
    resource_table(resource)
    body = await request.body()
    if len(body) > 2 * 1024 * 1024: raise HTTPException(413, 'configuration_too_large')
    try:
        import json
        value = json.loads(body)
        return await asyncio.to_thread(config_store().save, resource, ref, value, validate=validate_configuration)
    except (ValueError, KeyError, TypeError, RuntimeError, SQLAlchemyError):
        raise HTTPException(400, 'configuration_invalid') from None

@router.delete('/{resource}/{ref}')
async def delete_record(resource: str, ref: str, request: Request):
    await authorize(request)
    resource_table(resource)
    if resource == 'settings' or resource == 'capabilities' and ref == 'conversation':
        raise HTTPException(400, 'configuration_required')
    try:
        await asyncio.to_thread(config_store().delete, resource, ref)
    except (ValueError, SQLAlchemyError):
        raise HTTPException(409, 'configuration_in_use') from None
    return {'deleted':True}
