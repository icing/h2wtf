# h2wtf

what is going on with HTTP/2 requests in my Apache httpd server?

If you can reproduce a problem with light traffic on your server, use

```
LogLevel http2:trace2
```

to produce an `error.log` file and `h2wtf` will let you view what has gone on in regard 
to HTTP/2 requests.

### Aggregated Streams

To see the list of streams handled, when they were created/started/ended/reset/cleaned/destroyed and how many workers where in use at the time, use:

```
> python3 src/h2wtf.py -A error.log
Streams (total=92)
id                     created             started             ended              reset             cleanup           destroyed
1733364:1-1      0:00:21.001734   0w      +0.000100  1w      +0.000396  0w                 --      +0.000546  0w      +0.000593  0w
1733364:1-3      0:00:21.016014   0w      +0.000080  1w      +0.000313  2w                 --      +0.002385  0w      +0.002468  0w
1733364:1-5      0:00:21.016111   1w      +0.000176  2w      +0.000483  1w                 --      +0.002330  0w      +0.002382  0w
1733364:1-7      0:00:21.016152   1w      +0.000172  3w      +0.000423  2w                 --      +0.003442  0w      +0.003497  0w
1733364:1-9      0:00:21.016195   1w      +0.000166  3w      +0.000418  0w                 --      +0.028427  0w      +0.028462  0w
1733364:1-11     0:00:21.047003   0w      +0.000099  1w      +0.000395  1w                 --      +0.000605  0w      +0.000662  0w
```


### Streams Lifetimes

To see the log entries that create/run/end/clenaup streams, use:

```
> python3 src/h2wtf.py -L error.log
...time in relation to start of log file...
+ 0:00:51.507423 1733364/140152475207232 http2    trace3 [h2_stream.c(574)]       h2_stream(1-175,CLEANUP): destroy
+ 0:00:51.533480 1733364/140153775289920 http2    trace2 [h2_mplx.c(771)]         h2_mplx(17-177): request done, 26.278000 ms elapsed
+ 0:00:51.533491 1733364/140153775289920 http2    trace1 [h2_task.c(626)]         h2_task(17-179): process connection
+ 0:00:51.533666 1733364/140152475207232 http2    trace2 [h2_mplx.c(480)]         h2_stream(1-177,CLEANUP): cleanup
...
```

### A Specific Stream

To see the events related to a specific HTTP/2 stream, use (if the stream is number 3 on connection 1):

```
> python3 src/h2wtf.py -S 1-3 error.log
+ 0:00:21.016014 1733364/140153691362880 http2    debug  [h2_stream.c(542)]       AH03082: h2_stream(1-3,IDLE): created
+ 0:00:21.016016 1733364/140153691362880 http2    trace2 [h2_session.c(1955)]     h2_stream(1-3,IDLE): entered state
+ 0:00:21.016046 1733364/140153691362880 http2    trace1 [h2_stream.c(301)]       h2_stream(1-3,IDLE): transit to [OPEN]
+ 0:00:21.016048 1733364/140153691362880 http2    trace2 [h2_session.c(1955)]     h2_stream(1-3,OPEN): entered state
+ 0:00:21.016050 1733364/140153691362880 http2    trace1 [h2_stream.c(301)]       h2_stream(1-3,OPEN): transit to [HALF_CLOSED_REMOTE]
+ 0:00:21.016052 1733364/140153691362880 http2    trace1 [h2_stream.c(210)]       h2_stream(1-3,HALF_CLOSED_REMOTE): closing input
+ 0:00:21.016053 1733364/140153691362880 http2    trace2 [h2_session.c(1955)]     h2_stream(1-3,HALF_CLOSED_REMOTE): entered state
+ 0:00:21.016074 1733364/140153691362880 http2    trace1 [h2_stream.c(583)]       h2_stream(1-3,HALF_CLOSED_REMOTE): schedule GET https://localhost/styles.194b3660038d369a1ea7.css chunked=0
+ 0:00:21.016077 1733364/140153691362880 http2    trace1 [h2_mplx.c(672)]         h2_stream(1-3,HALF_CLOSED_REMOTE): process, added to q

```

### Frames

To see the HTTP/2 frames sent/received, use

```
> python3 src/h2wtf.py -F error.log
...time in relation to start of log file...
+ 0:00:51.467943 1733364/140152475207232 http2    debug  [h2_session.c(339)]      AH03066: h2_session(1,BUSY,8): recv FRAME[HEADERS[length=92, hend=1, stream=179, eos=1]], frames=111/1323 (r/s)
+ 0:00:51.472277 1733364/140152475207232 http2    debug  [h2_session.c(591)]      AH03068: h2_session(1,BUSY,8): sent FRAME[HEADERS[length=52, hend=1, stream=171, eos=0]], frames=112/1324 (r/s)
+ 0:00:51.472493 1733364/140152475207232 http2    debug  [h2_session.c(591)]      AH03068: h2_session(1,BUSY,8): sent FRAME[DATA[length=173, flags=1, stream=171, padlen=0]], frames=112/1325 (r/s
...
```
