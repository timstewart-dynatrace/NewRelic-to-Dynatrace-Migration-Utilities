"""Consolidated New Relic -> Dynatrace mapping tables.

This module is the single source of truth for every static mapping used
during NRQL-to-DQL migration:

* EVENT_TYPE_MAP  -- NR event type -> DT data source
* METRIC_MAP      -- NR metric field -> DT metric key
* METRIC_TRANSFORMS -- metrics that require calculated DQL expressions
* AGG_MAP         -- NR aggregation / function -> DQL equivalent
* ATTR_MAP        -- NR attribute name -> DT attribute name
* VIZ_MAP         -- NR visualization type -> DT visualization type

All keys that represent NR identifiers are **lower-cased** at lookup time
unless otherwise noted (ATTR_MAP preserves mixed case for some entries).
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "EVENT_TYPE_MAP",
    "METRIC_MAP",
    "METRIC_TRANSFORMS",
    "AGG_MAP",
    "ATTR_MAP",
    "VIZ_MAP",
]

# ---------------------------------------------------------------------------
# Event type to DT data source
# ---------------------------------------------------------------------------

EVENT_TYPE_MAP: dict[str, str] = {
    # APM/Transaction data
    'transaction': 'spans',
    'transactionerror': 'spans',
    'span': 'spans',

    # Metric data - use METRIC to trigger timeseries queries
    'metric': 'METRIC',
    'systemsample': 'METRIC',
    'processsample': 'METRIC',
    'networksample': 'METRIC',
    'storagesample': 'METRIC',

    # K8s samples - these are METRICS, not events
    'k8snodesample': 'K8S_NODE_METRIC',
    'k8scontainersample': 'K8S_WORKLOAD_METRIC',
    'k8spodsample': 'K8S_POD_METRIC',
    'k8sclustersample': 'K8S_CLUSTER_METRIC',
    'k8sdeploymentsample': 'K8S_WORKLOAD_METRIC',

    # Container metrics
    'containersample': 'METRIC',

    # Log data
    'log': 'logs',
    'logevent': 'logs',

    # Synthetic data
    'syntheticcheck': 'dt.synthetic.http.request',
    'syntheticsrequest': 'dt.synthetic.http.request',

    # Browser/RUM data
    'pageview': 'bizevents',
    'pageaction': 'bizevents',
    'browserinteraction': 'bizevents',
    'ajaxrequest': 'bizevents',
    'javascripterror': 'bizevents',

    # Lambda
    'awslambdainvocation': 'spans',

    # Custom events
    'nrcustomappevent': 'bizevents',

    # Infrastructure events
    'infrastructureevent': 'events',

    # Additional NR event types (from Grail data objects reference)
    'mobilesession': 'bizevents',
    'mobilecrash': 'bizevents',
    'mobilerequest': 'bizevents',
    'mobilehandledexception': 'bizevents',
    'servelesssample': 'METRIC',
    'nrevent': 'events',
    'nrcustomevent': 'bizevents',
    'relationship': 'spans',          # NR entity relationships -> trace links
    'nrauditevent': 'events',         # Audit logs -> events
    'nrdbquery': 'spans',             # DB query events -> spans
    'nrintegrationsample': 'METRIC',  # Integration metrics
}

# ---------------------------------------------------------------------------
# Metric field to DT metric key
# ---------------------------------------------------------------------------

METRIC_MAP: dict[str, str] = {
    # =========================================================================
    # SERVICE / APM METRICS
    # Grail: dt.service.request.response_time, dt.service.request.count,
    #        dt.service.request.failure_count
    # Classic (still works): builtin:service.response.time, etc.
    # =========================================================================

    # Response time / duration
    'duration': 'dt.service.request.response_time',
    'durationms': 'dt.service.request.response_time',
    'webduration': 'dt.service.request.response_time',
    'totaltime': 'dt.service.request.response_time',
    'responsetime': 'dt.service.request.response_time',
    # NR FROM Metric dotted names (normalized)
    'apmservicetransactionduration': 'dt.service.request.response_time',
    'apmserviceoverviewresponsetime': 'dt.service.request.response_time',

    # External/database duration -> NR-specific breakdown, DT doesn't split these
    # Map to response_time as closest equivalent; add warning in converter
    'externalduration': 'dt.service.request.response_time',
    'databaseduration': 'dt.service.request.response_time',
    'externalallweb': 'dt.service.request.response_time',

    # Error metrics
    'errorrate': 'dt.service.request.failure_count',      # NOTE: rate must be calculated from count+failure_count
    'errorcount': 'dt.service.request.failure_count',
    'apmserviceerrorcount': 'dt.service.request.failure_count',

    # Throughput / request count
    'throughput': 'dt.service.request.count',
    'requestsperminute': 'dt.service.request.count',
    'requestcount': 'dt.service.request.count',
    'apmservicetransactioncount': 'dt.service.request.count',
    'apmserviceoverviewthroughput': 'dt.service.request.count',

    # Apdex -> Classic only, NOT available on Grail
    'apdex': 'builtin:service.apdex',

    # =========================================================================
    # HOST METRICS -- CPU
    # Classic: builtin:host.cpu.*  |  Grail: dt.host.cpu.*
    # Ref: docs.dynatrace.com/docs/observe/infrastructure-observability/hosts/reference/metrics
    # =========================================================================
    'cpupercent': 'dt.host.cpu.usage',
    'cpuusagepercent': 'dt.host.cpu.usage',
    'cpusystempercent': 'dt.host.cpu.system',
    'cpuuserpercent': 'dt.host.cpu.user',
    'cpuidlepercent': 'dt.host.cpu.idle',
    'cpuiowaitpercent': 'dt.host.cpu.iowait',
    'cpustealpercent': 'dt.host.cpu.steal',
    'systemload': 'dt.host.cpu.load',
    'loadaverage1min': 'dt.host.cpu.load',
    'loadaverage5min': 'dt.host.cpu.load5m',
    'loadaverage15min': 'dt.host.cpu.load15m',
    # NR SystemSample normalized names
    'cpuutilization': 'dt.host.cpu.usage',
    # NR `host.*` dotted-prefix form (normalizes to `host<name>` after
    # `.replace(".", "")`). Added for gh #14 — these were reported as
    # Unknown-metric from `migrate.py compile`.
    'hostcpupercent': 'dt.host.cpu.usage',

    # =========================================================================
    # HOST METRICS -- MEMORY
    # Classic: builtin:host.mem.*  |  Grail: dt.host.memory.*
    # NOTE: Grail uses "memory" not "mem"
    # =========================================================================
    'memoryusedpercent': 'dt.host.memory.usage',
    'memoryutilization': 'dt.host.memory.usage',
    'hostmemoryusedpercent': 'dt.host.memory.usage',  # gh #14
    'memoryfreebytes': 'dt.host.memory.avail.bytes',
    'memoryfree': 'dt.host.memory.avail.bytes',
    'memoryfreepercent': 'dt.host.memory.avail.percent',
    'memoryused': 'dt.host.memory.used',
    'memoryusedbytes': 'dt.host.memory.used',       # Host context; K8s context handled separately
    'memorytotal': 'dt.host.memory.total',
    'memorytotalbytes': 'dt.host.memory.total',
    'swapused': 'dt.host.memory.swap.used',
    'swapfree': 'dt.host.memory.swap.avail',
    'swaptotal': 'dt.host.memory.swap.total',
    'pagefaults': 'dt.host.memory.avail.pfps',

    # =========================================================================
    # HOST METRICS -- DISK
    # Classic: builtin:host.disk.*  |  Grail: dt.host.disk.*
    # =========================================================================
    'diskusedpercent': 'dt.host.disk.used.percent',
    'diskutilization': 'dt.host.disk.used.percent',
    'hostdiskusedpercent': 'dt.host.disk.used.percent',  # gh #14
    'diskfreepercent': 'dt.host.disk.free',
    'diskused': 'dt.host.disk.used',
    'diskusedbytes': 'dt.host.disk.used',
    'diskfree': 'dt.host.disk.avail',
    'diskreadbytespersecond': 'dt.host.disk.bytes_read',
    'diskwritebytespersecond': 'dt.host.disk.bytes_written',
    'diskreadops': 'dt.host.disk.read_ops',
    'diskwriteops': 'dt.host.disk.write_ops',
    'diskutiltime': 'dt.host.disk.util_time',
    'diskqueuelength': 'dt.host.disk.queue_length',
    'inodesused': 'dt.host.disk.inodes_used',
    'inodesavailpercent': 'dt.host.disk.inodes_avail',

    # =========================================================================
    # HOST METRICS -- NETWORK
    # Classic: builtin:host.net.nic.*  |  Grail: dt.host.net.nic.*
    # =========================================================================
    'networkrxbytes': 'dt.host.net.nic.bytes_rx',
    'networktxbytes': 'dt.host.net.nic.bytes_tx',
    'networkreceivedpersecond': 'dt.host.net.nic.bytes_rx',
    'networksentpersecond': 'dt.host.net.nic.bytes_tx',
    'transmitbytespersecond': 'dt.host.net.nic.bytes_tx',
    'receivebytespersecond': 'dt.host.net.nic.bytes_rx',
    'networkreceiveerrors': 'dt.host.net.nic.packets.errors_rx',
    'networktransmiterrors': 'dt.host.net.nic.packets.errors_tx',
    'networkreceivedropped': 'dt.host.net.nic.packets.dropped_rx',
    'networktransmitdropped': 'dt.host.net.nic.packets.dropped_tx',

    # =========================================================================
    # KUBERNETES CONTAINER METRICS (Grail: dt.kubernetes.container.*)
    # These are the primary K8s metrics in Grail. Workload/node aggregation
    # is done via by:{k8s.workload.name} or by:{k8s.node.name} in the query.
    #
    # Ref: docs.dynatrace.com/docs/analyze-explore-automate/metrics/upgrade/kubernetes-metric-migration
    # Classic (DEPRECATED): builtin:kubernetes.workload.cpu_usage -> dt.kubernetes.container.cpu_usage
    # =========================================================================

    # CPU
    'k8scontainercpuusedcores': 'dt.kubernetes.container.cpu_usage',
    'k8scontainercpucoresutilization': 'dt.kubernetes.container.cpu_usage',
    'cpuusedcores': 'dt.kubernetes.container.cpu_usage',                      # NR K8sContainerSample field
    'containercpuusage': 'dt.kubernetes.container.cpu_usage',
    'cpucoresutilization': 'dt.kubernetes.container.cpu_usage',
    'cputhrottled': 'dt.kubernetes.container.cpu_throttled',

    # CPU Requests & Limits
    'cpurequestscores': 'dt.kubernetes.container.requests_cpu',
    'cpulimitscores': 'dt.kubernetes.container.limits_cpu',
    'requestscpu': 'dt.kubernetes.container.requests_cpu',
    'limitscpu': 'dt.kubernetes.container.limits_cpu',

    # Memory
    'k8scontainermemoryusedbytes': 'dt.kubernetes.container.memory_working_set',
    'k8scontainermemoryutilization': 'dt.kubernetes.container.memory_working_set',
    'containermemoryusedbytes': 'dt.kubernetes.container.memory_working_set',
    'memoryworkingsetbytes': 'dt.kubernetes.container.memory_working_set',     # NR K8sContainerSample

    # Memory Requests & Limits
    'memoryrequestsbytes': 'dt.kubernetes.container.requests_memory',
    'memorylimitsbytes': 'dt.kubernetes.container.limits_memory',
    'requestsmemory': 'dt.kubernetes.container.requests_memory',
    'limitsmemory': 'dt.kubernetes.container.limits_memory',

    # Container lifecycle
    'k8scontainerrestartcountdelta': 'dt.kubernetes.container.restarts',
    'k8scontainerrestartcount': 'dt.kubernetes.container.restarts',
    'restartcount': 'dt.kubernetes.container.restarts',
    'restartcountdelta': 'dt.kubernetes.container.restarts',
    'outofmemorykills': 'dt.kubernetes.container.oom_kills',
    'oomkills': 'dt.kubernetes.container.oom_kills',

    # Container readiness -> DT uses workload conditions, not per-container isReady
    'k8scontainerisready': 'dt.kubernetes.workload.conditions',
    'isready': 'dt.kubernetes.workload.conditions',

    # =========================================================================
    # KUBERNETES NODE METRICS (Grail: dt.kubernetes.node.*)
    # Node-level resource usage = aggregate container metrics by node:
    #   timeseries sum(dt.kubernetes.container.cpu_usage), by:{k8s.node.name}
    # Node allocatable resources have dedicated metrics.
    # =========================================================================

    # Node allocatable (these ARE dedicated node metrics)
    'allocatablecpucores': 'dt.kubernetes.node.cpu_allocatable',
    'allocatablecpuutilization': 'dt.kubernetes.node.cpu_allocatable',        # NOTE: utilization = usage/allocatable, needs calc
    'allocatablecpucoresutilization': 'dt.kubernetes.node.cpu_allocatable',   # NR variant with "Cores" in name
    'cpuallocatable': 'dt.kubernetes.node.cpu_allocatable',
    'allocatablememorybytes': 'dt.kubernetes.node.memory_allocatable',
    'allocatablememoryutilization': 'dt.kubernetes.node.memory_allocatable',   # NOTE: utilization needs calc
    'memoryallocatable': 'dt.kubernetes.node.memory_allocatable',
    'allocatablepods': 'dt.kubernetes.node.pods_allocatable',

    # Node memory (usage) -> In Grail, aggregate container metrics to node level
    # Map to container.memory_working_set; converter will add by:{k8s.node.name}
    'memoryavailablebytes': 'dt.kubernetes.container.memory_working_set',      # K8s context

    # =========================================================================
    # KUBERNETES POD METRICS
    # Pod-level = container metrics grouped by pod:
    #   timeseries sum(dt.kubernetes.container.cpu_usage), by:{k8s.pod.name}
    # =========================================================================
    'k8spodcpuusedbytes': 'dt.kubernetes.container.cpu_usage',
    'k8spodmemoryusedbytes': 'dt.kubernetes.container.memory_working_set',
    'podcpuusage': 'dt.kubernetes.container.cpu_usage',
    'podmemoryusage': 'dt.kubernetes.container.memory_working_set',

    # =========================================================================
    # KUBERNETES CLUSTER / WORKLOAD COUNTS
    # =========================================================================
    'podsrunning': 'dt.kubernetes.pods',
    'podsdesired': 'dt.kubernetes.workload.pods_desired',
    'containersrunning': 'dt.kubernetes.containers',

    # =========================================================================
    # KUBERNETES PERSISTENT VOLUME CLAIMS (Grail: dt.kubernetes.persistentvolumeclaim.*)
    # Maps NR filesystem metrics in K8s context
    # =========================================================================
    'fscapacitybytes': 'dt.kubernetes.persistentvolumeclaim.capacity',
    'fsusedbytes': 'dt.kubernetes.persistentvolumeclaim.used',
    'fsavailablebytes': 'dt.kubernetes.persistentvolumeclaim.available',
    'fscapacityutilization': 'dt.kubernetes.persistentvolumeclaim.used',      # NOTE: utilization needs calc
    # Inode metrics -> K8s node filesystem inodes
    'fsinodesfree': 'dt.host.disk.inodes_avail',
    'fsinodesused': 'dt.host.disk.inodes_used',
    'fsinodes': 'dt.host.disk.inodes_total',

    # =========================================================================
    # CONTAINER METRICS (non-K8s, from NR ContainerSample)
    # Classic: builtin:containers.*  |  Grail: dt.containers.*
    # =========================================================================
    'containercpupercent': 'dt.containers.cpu.usage_user_time',
    'containermemorypercent': 'dt.containers.memory.resident_set_bytes',

    # =========================================================================
    # NR `FROM Metric` DOTTED METRIC NAMES
    # These appear in queries like: FROM Metric SELECT latest(`apm.service.overview.responseTime`)
    # Normalized: dots and underscores stripped, lowercased
    # =========================================================================

    # APM dotted metrics
    'apmserviceoverviewresponsetime50': 'dt.service.request.response_time',
    'apmserviceoverviewresponsetime99': 'dt.service.request.response_time',
    'apmservicetransactiondurationaverage': 'dt.service.request.response_time',
    'apmserviceerrorrateerrorrate': 'dt.service.request.failure_count',

    # Host dotted metrics (NR agent)
    'hostsystemcpuutilization': 'dt.host.cpu.usage',
    'hostmemorytotal': 'dt.host.memory.total',
    'hostnettransmitbytes': 'dt.host.net.nic.bytes_tx',
    'hostnetreceivebytes': 'dt.host.net.nic.bytes_rx',

    # K8s dotted metrics (NR Kubernetes integration)
    # These come from queries like: FROM Metric SELECT latest(`k8s.container.memoryUsedBytes`)
    'k8scontainercpuusage': 'dt.kubernetes.container.cpu_usage',
    'k8snodecpuusage': 'dt.kubernetes.container.cpu_usage',                         # aggregate to node
    'k8snodememoryusage': 'dt.kubernetes.container.memory_working_set',              # aggregate to node
    'k8spodcpuusage': 'dt.kubernetes.container.cpu_usage',
    'k8spodmemoryusage': 'dt.kubernetes.container.memory_working_set',

    # =========================================================================
    # SERVICE METRICS -- Extended (Verified: DT Service Metrics Migration Guide Dec 2025)
    # Key insight: Many NR service sub-metrics map to dt.service.request.count
    # with dimensional filters (failed, http.response.status_code, endpoint.name)
    # =========================================================================

    # External/backend call metrics -> DT tracks via spans, not separate metrics
    # NR externalDuration, externalCallCount -> fetch spans with span.kind="client"
    'externalcallcount': 'dt.service.request.count',         # NOTE: needs filter span.kind="client"
    'externalthroughput': 'dt.service.request.count',
    'externalresponsetime': 'dt.service.request.response_time',

    # Database call metrics -> DT tracks via spans with db.statement
    # NR databaseCallCount -> fetch spans | filter isNotNull(db.statement)
    'databasecallcount': 'dt.service.request.count',          # NOTE: needs filter on db spans
    'databaseresponsetime': 'dt.service.request.response_time',

    # Error rate breakdown -> DT uses dimensional filters
    'http4xxerrorrate': 'dt.service.request.count',           # NOTE: needs filter http.response.status_code 400-499
    'http5xxerrorrate': 'dt.service.request.count',           # NOTE: needs filter http.response.status_code 500-599
    'httperrorcount': 'dt.service.request.failure_count',
    'failurerate': 'dt.service.request.failure_count',
    'failurecount': 'dt.service.request.failure_count',
    'successcount': 'dt.service.request.count',               # NOTE: needs filter failed==false
    'successrate': 'dt.service.request.count',

    # Key request / endpoint metrics
    'webtransactiontotaltime': 'dt.service.request.response_time',
    'webtransactioncount': 'dt.service.request.count',
    'webrequestcount': 'dt.service.request.count',

    # =========================================================================
    # PROCESS METRICS (Verified: DT Built-in Metrics on Grail Feb 2026)
    # NR ProcessSample fields -> dt.process.* on Grail
    # NOTE: builtin:process.cpu/memory NOT on Grail; use dt.process.* instead
    # Process metrics replace builtin:tech.generic prefix
    # =========================================================================

    # Process CPU -> NR ProcessSample cpuPercent
    'processcpupercent': 'dt.process.cpu.usage',
    'processcpuuserpercent': 'dt.process.cpu.user',
    'processcpusystempercent': 'dt.process.cpu.system',

    # Process Memory
    'processmemoryrssbytes': 'dt.process.memory.rss',
    'processmemoryusedbytes': 'dt.process.memory.rss',
    'processmemoryvirtualsize': 'dt.process.memory.virtual',
    'memoryresidentsize': 'dt.process.memory.rss',
    'memoryvirtualsize': 'dt.process.memory.virtual',

    # Process Network
    'processnetreceivedpersecond': 'dt.process.network.bytes_rx',
    'processnetsentpersecond': 'dt.process.network.bytes_tx',
    'iototalreadbytes': 'dt.process.io.read_bytes',
    'iototalwritebytes': 'dt.process.io.write_bytes',
    'ioreadbytespersecond': 'dt.process.io.read_bytes',
    'iowritebytespersecond': 'dt.process.io.write_bytes',
    'ioreadcountpersecond': 'dt.process.io.read_ops',
    'iowritecountpersecond': 'dt.process.io.write_ops',

    # Process Threads/FD
    'threadcount': 'dt.process.threads',
    'filedescriptorcount': 'dt.process.open_file_descriptors',

    # Process Availability
    'processavailability': 'dt.process.availability',

    # Process network sessions
    'networksessionsestablished': 'dt.process.network.sessions.established',
    'networksessionsresetlocal': 'dt.process.network.sessions.reset_local',
    'networksessionsresetremote': 'dt.process.network.sessions.reset_remote',

    # =========================================================================
    # SYNTHETIC METRICS (Verified: DT HTTP Monitor Metrics in Synthetic on Grail)
    # NR SyntheticCheck fields -> dt.synthetic.* metrics
    # =========================================================================

    # HTTP monitor metrics
    'syntheticduration': 'dt.synthetic.http.request.duration',
    'syntheticresponsetime': 'dt.synthetic.http.request.duration',
    'monitorresponsetime': 'dt.synthetic.http.request.duration',
    'monitorduration': 'dt.synthetic.http.request.duration',
    'checkduration': 'dt.synthetic.http.request.duration',
    'syntheticavailability': 'dt.synthetic.http.availability',
    'monitoravailability': 'dt.synthetic.http.availability',
    'syntheticexecutions': 'dt.synthetic.http.executions',

    # Browser monitor metrics
    'browserduration': 'dt.synthetic.browser.duration',
    'browseravailability': 'dt.synthetic.browser.availability',

    # Multi-protocol / ICMP
    'icmproundtriptime': 'dt.synthetic.multi_protocol.icmp.round_trip_time',
    'icmpavailability': 'dt.synthetic.multi_protocol.icmp.success_rate',
    'icmppacketssent': 'dt.synthetic.multi_protocol.icmp.packets_sent',
    'icmppacketsreceived': 'dt.synthetic.multi_protocol.icmp.packets_received',
    'dnsresolutiontime': 'dt.synthetic.multi_protocol.dns.resolution_time',
    'tcpconnectiontime': 'dt.synthetic.multi_protocol.tcp.connection_time',

    # =========================================================================
    # BROWSER / RUM METRICS (NR PageView/BrowserInteraction -> DT RUM)
    # DT stores browser data differently -- primarily in user sessions
    # These map to the closest Grail equivalents
    # =========================================================================

    'domprocessingtime': 'dt.rum.action.duration.dom_processing',
    'pageloadtime': 'dt.rum.action.duration',
    'firstcontentfulpaint': 'dt.rum.action.duration.first_contentful_paint',
    'firstpaint': 'dt.rum.action.duration.first_paint',
    'largestcontentfulpaint': 'dt.rum.action.duration.largest_contentful_paint',
    'cumulativelayoutshift': 'dt.rum.action.cumulative_layout_shift',
    'firstinputdelay': 'dt.rum.action.first_input_delay',
    'interactiontonextpaint': 'dt.rum.action.interaction_to_next_paint',
    'timetointeractive': 'dt.rum.action.duration.load_event_end',
    'backendtime': 'dt.rum.action.duration.server',
    'frontendtime': 'dt.rum.action.duration.frontend',
    'networktime': 'dt.rum.action.duration.network',
    'connectionsetuptime': 'dt.rum.action.duration.network',

    # AJAX/XHR
    'ajaxresponsetime': 'dt.rum.xhr.duration',
    'ajaxcallcount': 'dt.rum.xhr.count',

    # JavaScript errors
    'javascripterrorcount': 'dt.rum.jserror.count',
    'jserrorcount': 'dt.rum.jserror.count',

    # =========================================================================
    # AWS CLOUD METRICS (Verified: DT Built-in Metrics on Grail)
    # NR AWS integration -> dt.cloud.aws.*
    # =========================================================================

    # Lambda
    'awslambdaduration': 'dt.cloud.aws.lambda.duration',
    'awslambdainvocations': 'dt.cloud.aws.lambda.invocations',
    'awslambdaerrors': 'dt.cloud.aws.lambda.errors',
    'awslambdathrottles': 'dt.cloud.aws.lambda.throttlers',
    'awslambdaconcurrentexecutions': 'dt.cloud.aws.lambda.conc_executions',

    # RDS
    'awsrdscpuutilization': 'dt.cloud.aws.rds.cpu.usage',
    'awsrdsconnections': 'dt.cloud.aws.rds.connections',
    'awsrdsfreeablememory': 'dt.cloud.aws.rds.memory.freeable',
    'awsrdsreadlatency': 'dt.cloud.aws.rds.latency.read',
    'awsrdswritelatency': 'dt.cloud.aws.rds.latency.write',
    'awsrdsreadiops': 'dt.cloud.aws.rds.ops.read',
    'awsrdswriteiops': 'dt.cloud.aws.rds.ops.write',

    # ALB/ELB
    'awsalbhealthyhostcount': 'dt.cloud.aws.elb.hosts.healthy',
    'awsalbunhealthyhostcount': 'dt.cloud.aws.elb.hosts.unhealthy',
    'awsalbrequestcount': 'dt.cloud.aws.alb.requests',
    'awsalbresponsetime': 'dt.cloud.aws.alb.resp_time',
    'awsalb5xxcount': 'dt.cloud.aws.alb.errors.alb.http5xx',
    'awsalb4xxcount': 'dt.cloud.aws.alb.errors.alb.http4xx',
    'awsalbactiveconnections': 'dt.cloud.aws.alb.connections.active',

    # EC2
    'awsec2cpuutilization': 'dt.cloud.aws.ec2.cpu.usage',
    'awsec2networkrx': 'dt.cloud.aws.ec2.net.rx',
    'awsec2networktx': 'dt.cloud.aws.ec2.net.tx',
    'awsec2diskreadops': 'dt.cloud.aws.ec2.disk.read_ops',
    'awsec2diskwriteops': 'dt.cloud.aws.ec2.disk.write_ops',

    # DynamoDB
    'awsdynamodbconsumedreadrcu': 'dt.cloud.aws.dynamo.capacity_units.consumed.read',
    'awsdynamodbconsumedwritewcu': 'dt.cloud.aws.dynamo.capacity_units.consumed.write',
    'awsdynamodbthrottledrequests': 'dt.cloud.aws.dynamo.requests.throttled',
    'awsdynamodblatency': 'dt.cloud.aws.dynamo.requests.latency',

    # S3 -- no dedicated Grail metrics for S3 (use extension metrics)

    # =========================================================================
    # HOST AVAILABILITY (Verified: DT Built-in Metrics on Grail)
    # =========================================================================
    'hostavailability': 'dt.host.availability',
    'hostuptime': 'dt.host.uptime',
}

# ---------------------------------------------------------------------------
# METRIC TRANSFORMS -- Calculated Expressions
#
# Entries here override the simple METRIC_MAP lookup when a metric requires
# a multi-metric calculation, unit conversion, or other post-processing.
# ---------------------------------------------------------------------------

METRIC_TRANSFORMS: dict[str, dict[str, Any]] = {
    # -------------------------------------------------------------------------
    # ERROR RATE -- NR has errorRate as first-class field; DT must calculate it
    # NR: SELECT latest(errorRate) FROM Transaction
    # DT: (failure_count / total_count) * 100
    # -------------------------------------------------------------------------
    'errorrate': {
        'type': 'calculated',
        'dql': (
            "timeseries {failures = sum(dt.service.request.failure_count), "
            "total = sum(dt.service.request.count)}{by}{filter}\n"
            "| fieldsAdd error_rate = else(toDouble(failures) / toDouble(total) * 100.0, 0.0)"
        ),
        'dql_single': (
            "timeseries {fail = sum(dt.service.request.failure_count), "
            "total = sum(dt.service.request.count)}{by}{filter}\n"
            "| fieldsAdd error_rate = else(toDouble(fail) / toDouble(total) * 100.0, 0.0)"
        ),
        'note': 'errorRate calculated: (failure_count / request_count) * 100',
        'confidence': 'HIGH',
    },

    # -------------------------------------------------------------------------
    # K8s NODE CPU UTILIZATION -- NR has allocatableCpuUtilization as %;
    # DT requires: sum(container.cpu_usage by node) / node.cpu_allocatable * 100
    # -------------------------------------------------------------------------
    'allocatablecpuutilization': {
        'type': 'multi_metric',
        'dql': (
            "// CPU Utilization = (container CPU usage / node allocatable) * 100\n"
            "timeseries {usage = sum(dt.kubernetes.container.cpu_usage), "
            "allocatable = avg(dt.kubernetes.node.cpu_allocatable)}, by: {k8s.node.name}{filter}\n"
            "| fieldsAdd cpu_utilization_pct = (toDouble(usage) / toDouble(allocatable)) * 100.0"
        ),
        'note': 'Node CPU utilization calculated from container usage / node allocatable',
        'confidence': 'MEDIUM',
    },
    # Variant: NR also uses allocatableCpuCoresUtilization (with "Cores")
    'allocatablecpucoresutilization': {
        'type': 'multi_metric',
        'dql': (
            "// CPU Utilization = (container CPU usage / node allocatable) * 100\n"
            "timeseries {usage = sum(dt.kubernetes.container.cpu_usage), "
            "allocatable = avg(dt.kubernetes.node.cpu_allocatable)}, by: {k8s.node.name}{filter}\n"
            "| fieldsAdd cpu_utilization_pct = (toDouble(usage) / toDouble(allocatable)) * 100.0"
        ),
        'note': 'Node CPU utilization calculated from container usage / node allocatable',
        'confidence': 'MEDIUM',
    },

    # -------------------------------------------------------------------------
    # K8s NODE MEMORY UTILIZATION -- same pattern as CPU
    # NR: latest(allocatableMemoryUtilization)
    # DT: sum(container.memory_working_set by node) / node.memory_allocatable * 100
    # -------------------------------------------------------------------------
    'allocatablememoryutilization': {
        'type': 'multi_metric',
        'dql': (
            "// Memory Utilization = (container memory working set / node allocatable) * 100\n"
            "timeseries {usage = sum(dt.kubernetes.container.memory_working_set), "
            "allocatable = avg(dt.kubernetes.node.memory_allocatable)}, by: {k8s.node.name}{filter}\n"
            "| fieldsAdd memory_utilization_pct = (toDouble(usage) / toDouble(allocatable)) * 100.0"
        ),
        'note': 'Node memory utilization calculated from container working set / node allocatable',
        'confidence': 'MEDIUM',
    },

    # -------------------------------------------------------------------------
    # K8s FILESYSTEM UTILIZATION -- NR has fsCapacityUtilization as %;
    # DT: pvc.used / pvc.capacity * 100
    # -------------------------------------------------------------------------
    'fscapacityutilization': {
        'type': 'multi_metric',
        'dql': (
            "// Filesystem utilization = (PVC used / PVC capacity) * 100\n"
            "timeseries {used = sum(dt.kubernetes.persistentvolumeclaim.used), "
            "cap = sum(dt.kubernetes.persistentvolumeclaim.capacity)}{by}{filter}\n"
            "| fieldsAdd fs_utilization_pct = (toDouble(used) / toDouble(cap)) * 100.0"
        ),
        'note': 'PVC utilization calculated from used / capacity',
        'confidence': 'MEDIUM',
    },

    # -------------------------------------------------------------------------
    # K8s CONTAINER CPU -- Unit conversion
    # NR reports in CORES (millicores). DT reports in NANOSECONDS per minute.
    # Conversion: DT_ns_per_min -> cores = value / (60 * 1e9)
    # We add a fieldsAdd to convert units after the timeseries query.
    # -------------------------------------------------------------------------
    'cpuusedcores': {
        'type': 'unit_convert',
        'metric': 'dt.kubernetes.container.cpu_usage',
        'post_calc': "| fieldsAdd cpu_cores = toDouble({alias}) / 60000000000.0",
        'note': 'DT reports CPU in ns/min; converted to cores: value / (60 * 1e9)',
        'confidence': 'HIGH',
    },
    'k8scontainercpuusedcores': {
        'type': 'unit_convert',
        'metric': 'dt.kubernetes.container.cpu_usage',
        'post_calc': "| fieldsAdd cpu_cores = toDouble({alias}) / 60000000000.0",
        'note': 'DT reports CPU in ns/min; converted to cores: value / (60 * 1e9)',
        'confidence': 'HIGH',
    },

    # -------------------------------------------------------------------------
    # K8s CONTAINER CPU UTILIZATION -- Needs limits comparison
    # NR: cpuCoresUtilization = (cpuUsedCores / cpuLimitCores) * 100
    # DT: (cpu_usage / limits_cpu) * 100
    # -------------------------------------------------------------------------
    'cpucoresutilization': {
        'type': 'multi_metric',
        'dql': (
            "// Container CPU utilization = (usage / limit) * 100\n"
            "timeseries {usage = avg(dt.kubernetes.container.cpu_usage), "
            "lim = avg(dt.kubernetes.container.limits_cpu)}{by}{filter}\n"
            "| fieldsAdd cpu_utilization_pct = (toDouble(usage) / toDouble(lim)) * 100.0"
        ),
        'note': 'Container CPU utilization calculated from usage / limits',
        'confidence': 'MEDIUM',
    },
    'k8scontainercpucoresutilization': {
        'type': 'multi_metric',
        'dql': (
            "// Container CPU utilization = (usage / limit) * 100\n"
            "timeseries {usage = avg(dt.kubernetes.container.cpu_usage), "
            "lim = avg(dt.kubernetes.container.limits_cpu)}{by}{filter}\n"
            "| fieldsAdd cpu_utilization_pct = (toDouble(usage) / toDouble(lim)) * 100.0"
        ),
        'note': 'Container CPU utilization calculated from usage / limits',
        'confidence': 'MEDIUM',
    },

    # -------------------------------------------------------------------------
    # K8s CONTAINER MEMORY UTILIZATION -- Needs limits comparison
    # NR: memoryUtilization = (memoryUsedBytes / memoryLimitBytes) * 100
    # -------------------------------------------------------------------------
    'k8scontainermemoryutilization': {
        'type': 'multi_metric',
        'dql': (
            "// Container memory utilization = (working_set / limit) * 100\n"
            "timeseries {usage = avg(dt.kubernetes.container.memory_working_set), "
            "lim = avg(dt.kubernetes.container.limits_memory)}{by}{filter}\n"
            "| fieldsAdd memory_utilization_pct = (toDouble(usage) / toDouble(lim)) * 100.0"
        ),
        'note': 'Container memory utilization calculated from working_set / limits',
        'confidence': 'MEDIUM',
    },
    'memoryutilization': {
        'type': 'multi_metric',
        'dql': (
            "// Container memory utilization = (working_set / limit) * 100\n"
            "timeseries {usage = avg(dt.kubernetes.container.memory_working_set), "
            "lim = avg(dt.kubernetes.container.limits_memory)}{by}{filter}\n"
            "| fieldsAdd memory_utilization_pct = (toDouble(usage) / toDouble(lim)) * 100.0"
        ),
        'note': 'Container memory utilization calculated from working_set / limits',
        'confidence': 'MEDIUM',
    },

    # -------------------------------------------------------------------------
    # NR externalDuration / databaseDuration -- NR-specific breakdowns
    # DT doesn't separate external vs DB call time as a builtin metric.
    # Map to response_time with explanatory note.
    # -------------------------------------------------------------------------
    'externalduration': {
        'type': 'unit_convert',
        'metric': 'dt.service.request.response_time',
        'post_calc': '',
        'note': 'NR externalDuration has no DT equivalent; mapped to total response_time. Use span analytics for call breakdown.',
        'confidence': 'LOW',
    },
    'databaseduration': {
        'type': 'unit_convert',
        'metric': 'dt.service.request.response_time',
        'post_calc': '',
        'note': 'NR databaseDuration has no DT equivalent; mapped to total response_time. Use span analytics for DB call time.',
        'confidence': 'LOW',
    },
}

# ---------------------------------------------------------------------------
# Aggregation function mapping
# ---------------------------------------------------------------------------

AGG_MAP: dict[str, str] = {
    # Basic aggregations
    'count': 'count()',
    'sum': 'sum',
    'average': 'avg',
    'avg': 'avg',
    'max': 'max',
    'min': 'min',
    'percentile': 'percentile',
    'stddev': 'stddev',
    'rate': 'rate',

    # NR-specific -> DQL equivalents
    'latest': 'takeLast',      # DQL uses takeLast() for latest value
    'earliest': 'takeFirst',   # DQL uses takeFirst() for earliest value
    'last': 'takeLast',        # Alias
    'first': 'takeFirst',      # Alias
    'uniquecount': 'countDistinct',
    'uniques': 'collectDistinct',
    'median': 'percentile',    # Note: use percentile(field, 50)

    # String functions
    'concat': 'concat',
    'lower': 'lower',
    'upper': 'upper',
    'substring': 'substring',
    'length': 'stringLength',   # DQL uses stringLength() not strlen()
    'capture': 'extract',       # Regex capture
    'aparse': 'parse',          # Anchor parse

    # Math functions
    'abs': 'abs',
    'ceil': 'ceil',
    'floor': 'floor',
    'round': 'round',
    'sqrt': 'sqrt',
    'pow': 'power',        # DQL uses power() not pow()
    'log': 'log',          # Both use log() for natural log
    'log10': 'log10',
    'exp': 'exp',

    # Time functions
    'dateOf': 'formatTimestamp',
    'hourOf': 'getHour',
    'minuteOf': 'getMinute',
    'dayOfWeek': 'getDayOfWeek',
    'weekOf': 'getWeekOfYear',  # DQL uses getWeekOfYear() not getWeek()
    'monthOf': 'getMonth',
    'yearOf': 'getYear',

    # Type conversion
    'numeric': 'toDouble',
    'string': 'toString',

    # Post-preprocess aliases (preprocess may have already renamed)
    'countdistinct': 'countDistinct',
    'collectdistinct': 'collectDistinct',

    # Additional DQL aggregation functions (from Grail function reference)
    'countif': 'countIf',
    'variance': 'variance',
    'correlation': 'correlation',
    'collectarray': 'collectArray',
    'takeany': 'takeAny',
    'takemax': 'takeMax',
    'takemin': 'takeMin',
    'countdistinctapprox': 'countDistinctApprox',
    'countdistinctexact': 'countDistinctExact',

    # Additional string functions (from Grail function reference)
    'indexof': 'indexOf',
    'lastindexof': 'lastIndexOf',
    'stringlength': 'stringLength',
    'replacestring': 'replaceString',
    'replacepattern': 'replacePattern',
    'splitstring': 'splitString',
    'startswith': 'startsWith',
    'endswith': 'endsWith',
    'contains': 'contains',
    'matchesvalue': 'matchesValue',
    'matchesphrase': 'matchesPhrase',
    'matchespattern': 'matchesPattern',
    'trim': 'trim',
    'levenshteindistance': 'levenshteinDistance',

    # Additional time functions (from Grail function reference)
    'getdayofmonth': 'getDayOfMonth',
    'getdayofyear': 'getDayOfYear',
    'getsecond': 'getSecond',
    'formattimestamp': 'formatTimestamp',

    # Array functions (from Grail function reference)
    'arrayavg': 'arrayAvg',
    'arraymax': 'arrayMax',
    'arraymin': 'arrayMin',
    'arraymedian': 'arrayMedian',
    'arrayfirst': 'arrayFirst',
    'arraylast': 'arrayLast',
    'arrayconcat': 'arrayConcat',
    'arraydistinct': 'arrayDistinct',
    'arrayflatten': 'arrayFlatten',
    'arraydelta': 'arrayDelta',
    'arraycumulativesum': 'arrayCumulativeSum',
    'arraymovingavg': 'arrayMovingAvg',

    # Boolean/conditional (from Grail function reference)
    'isnull': 'isNull',
    'isnotnull': 'isNotNull',
    'coalesce': 'coalesce',

    # Type conversion (from Grail function reference)
    'tolong': 'toLong',
    'todouble': 'toDouble',
    'toboolean': 'toBoolean',
    'totimestamp': 'toTimestamp',
    'toduration': 'toDuration',
}

# ---------------------------------------------------------------------------
# Attribute mapping NR -> DT
# ---------------------------------------------------------------------------

ATTR_MAP: dict[str, str] = {
    # K8s attributes (longer matches first)
    'k8s.containername': 'k8s.container.name',
    'k8s.podname': 'k8s.pod.name',
    'k8s.clustername': 'k8s.cluster.name',
    'k8s.deploymentname': 'k8s.deployment.name',
    'k8s.namespacename': 'k8s.namespace.name',
    'k8s.nodename': 'k8s.node.name',
    # NR K8s attributes without k8s. prefix
    'containername': 'k8s.container.name',
    'clustername': 'k8s.cluster.name',
    'clusterName': 'k8s.cluster.name',
    'namespace': 'k8s.namespace.name',
    'namespaceName': 'k8s.namespace.name',
    'podname': 'k8s.pod.name',
    'podName': 'k8s.pod.name',
    'nodename': 'k8s.node.name',
    'nodeName': 'k8s.node.name',
    'jobname': 'k8s.job.name',
    'jobName': 'k8s.job.name',
    'deploymentname': 'k8s.deployment.name',
    'deploymentName': 'k8s.deployment.name',

    # NOTE: K8s METRIC mappings (cpuUsedCores -> dt.kubernetes.*, memoryUsedBytes -> dt.host.memory.*)
    # are in METRIC_MAP above. Do NOT duplicate here.
    # The deprecated builtin:kubernetes.* metrics do NOT work in Grail DQL queries.

    # APM/Transaction attributes
    'transactionname': 'span.name',
    'name': 'span.name',  # When used in Transaction context
    'appName': 'service.name',
    'appname': 'service.name',
    'duration': 'duration',
    'duration.ms': 'duration',  # Handle unit conversion context
    'databaseDuration': 'db.duration',
    'externalDuration': 'http.duration',
    'host': 'host.name',
    'httpResponseCode': 'http.response.status_code',
    # Note: 'error' field is intentionally NOT mapped here as it's too generic
    # and matches inside strings. Use error.message or check error == true explicitly.
    'error.message': 'error.message',
    'entityGuid': 'dt.entity.service',

    # HTTP/Service attributes
    'request.uri': 'http.request.path',
    'request.url': 'http.request.path',
    'request.method': 'http.request.method',
    'http.statuscode': 'http.response.status_code',
    'httpresponsecode': 'http.response.status_code',
    'response.status': 'http.response.status_code',
    'http.method': 'http.request.method',
    'httpmethod': 'http.request.method',
    'http.url': 'http.request.path',
    'httpurl': 'http.request.path',

    # Host/Infrastructure attributes
    'fullhostname': 'host.name',
    'hostname': 'host.name',
    'cpuPercent': 'host.cpu.usage',
    'memoryUsedPercent': 'host.memory.usage',
    'diskUsedPercent': 'host.disk.usage',

    # Entity attributes
    'entityname': 'entity.name',
    'entity.name': 'entity.name',

    # Error attributes
    'errormessage': 'error.message',
    'error.class': 'error.type',
    'errorclass': 'error.type',

    # Log attributes
    'logmessage': 'content',
    'log.message': 'content',
    'message': 'content',
    'loglevel': 'loglevel',
    'severity': 'loglevel',
    'log.level': 'loglevel',
    'level': 'loglevel',

    # Service/App attributes
    'servicename': 'service.name',
    'application': 'service.name',
    'service': 'service.name',

    # Cloud attributes
    'awsregion': 'cloud.region',
    'aws.region': 'cloud.region',
    'regionname': 'cloud.region',
    'provider.accountid': 'cloud.account.id',
    'environment': 'environment',
    'env': 'environment',

    # Browser/RUM attributes
    'session': 'session.id',
    'pageUrl': 'page.url',
    'userAgent': 'user_agent',
    'countryCode': 'geo.country',
    'city': 'geo.city',
}

# ---------------------------------------------------------------------------
# Visualization mapping NR -> DT
# ---------------------------------------------------------------------------

VIZ_MAP: dict[str, str] = {
    'viz.line': 'lineChart',
    'viz.area': 'areaChart',
    'viz.stacked-area': 'areaChart',
    'viz.bar': 'barChart',
    'viz.stacked-bar': 'barChart',
    'viz.billboard': 'singleValue',
    'viz.pie': 'pieChart',
    'viz.table': 'table',
    'viz.markdown': 'markdown',
    'viz.heatmap': 'honeycomb',
    'viz.histogram': 'histogram',
    'viz.json': 'table',
    'viz.bullet': 'gauge',
    'viz.funnel': 'table',  # No funnel in DT
    'viz.scatter': 'scatterPlot',
}
