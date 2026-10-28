"""Conservative endpoint aliases backed by the PBX extension inventory."""
import re


def canonical(interface,inventory):
    extensions=[row for row in (inventory or {}).get('endpoints',[]) if row.get('category')=='extension']
    phones={row['technology']+'/'+row['endpoint'] for row in extensions}
    if interface in phones:return interface
    local=re.fullmatch(r'Local/([^@/]+)@[^/]+(?:/n)?',interface)
    extension=local.group(1) if local else interface if re.fullmatch(r'[0-9]{1,20}',interface) else None
    matches={row['technology']+'/'+row['endpoint'] for row in extensions if row['endpoint']==extension}
    return next(iter(matches)) if len(matches)==1 else interface


def aliases(interfaces,inventory):
    """Expand assigned interfaces only through an unambiguous extension."""
    result=set(interfaces)
    for interface in interfaces:
        phone=canonical(interface,inventory)
        result.add(phone)
        if phone!=interface or phone.startswith(('PJSIP/','SIP/')):
            extension=phone.split('/',1)[-1]
            if canonical(extension,inventory)==phone:
                result.add(extension)
                result.add('Local/'+extension+'@from-queue/n')
                result.add('Local/'+extension+'@from-queue')
    if len(result)>64:raise ValueError('report_identity_scope_limit')
    return tuple(sorted(result))


def parties(channel,dstchannel,inventory):
    """Classify only explicitly observed endpoint definitions, never numbers."""
    endpoints={row['technology']+'/'+row['endpoint']:row['category']
               for row in (inventory or {}).get('endpoints',[])}
    def endpoint(value):
        if value in endpoints:return value
        base,separator,suffix=str(value).rpartition('-')
        return base if separator and re.fullmatch('[0-9a-fA-F]+',suffix) and base in endpoints else None
    origin,destination=endpoint(channel),endpoint(dstchannel)
    first,last=endpoints.get(origin),endpoints.get(destination)
    direction=('outbound' if (first,last)==('extension','trunk') else
               'inbound' if (first,last)==('trunk','extension') else
               'internal' if (first,last)==('extension','extension') else 'unknown')
    return dict(agent=origin if first=='extension' else destination if last=='extension' else '',
                direction=direction,inventory_observed=(inventory or {}).get('observed_at'))
