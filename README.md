# h2wtf

what is going on with HTTP/2 requests in my Apache httpd server?

If you can reproduce a problem with light traffic on your server, use

```
LogLevel http2:trace2
```

to produce an `error.log` file and `h2wtf` will let you view what has gone on in regard 
to HTTP/2 requests.



### All H2 Reqeusts

To see the list of requests handled and what happened at particular times, use:

```
> python3 src/h2wtf.py error.log
Streams (total=92)
id               created                          scheduled           started             ended              reset             cleanup           destroyed
1733364-1-1      2021-07-02 16:58:21.014361 0w      +0.000047  0w      +0.000100  1w      +0.000396  0w            --           +0.000546  0w      +0.000593  0w
1733364-1-3      2021-07-02 16:58:21.028641 0w      +0.000060  0w      +0.000080  1w      +0.000313  2w            --           +0.002385  0w      +0.002468  0w
1733364-1-5      2021-07-02 16:58:21.028738 1w      +0.000113  1w      +0.000176  2w      +0.000483  1w            --           +0.002330  0w      +0.002382  0w
1733364-1-7      2021-07-02 16:58:21.028779 1w      +0.000079  1w      +0.000172  3w      +0.000423  2w            --           +0.003442  0w      +0.003497  0w
1733364-1-9      2021-07-02 16:58:21.028822 1w      +0.000087  1w      +0.000166  3w      +0.000418  0w            --           +0.028427  0w      +0.028462  0w
```

This lists all requests found in the log file with the following columns:

 * `id`: the global identifier of a request (aka. h2 *stream*). This is `<process id>-<session id>-<stream number>`.
 * `created`: the timestamp the request was received. This is the time the (first) `HEADER` frame was recognized.
 * `scheduled`: the time relative to `created` when all headers were received and the request was put into the processing queue.
 * `started`: the time relative to `created` when a h2 worker started processing that request
 * `ended`: the time relative to `created` when the h2 worker was done processing that request
 * `reset`: the time relative to `created` when the client aborted the stream via a `RST_STREAM` frame.
 * `cleanup`: the time relative to `created` when the request was fully handled on the main connection.
 * `destroyed`: the time relative to `created` when all resources related to the request are freed. This only happens after `cleanup` and `ended`.
 
The `0w` or `3w` added in the columns gives the number of h2 workers busy at that time in that particular process. This is not 100% exact since workers might have already been busy when the given log file was recorded.

### Specific Requests

To see this summary for specific requests, you given the identifiers on the command line with `-S`:

```
> python3 src/h2wtf.py -S 1-3,5 error.log
Streams (total=2)
id               created                          scheduled           started             ended              reset             cleanup           destroyed
1733364-1-3      2021-07-02 16:58:21.028641 0w      +0.000060  0w      +0.000080  1w      +0.000313  2w            --           +0.002385  0w      +0.002468  0w
1733364-1-5      2021-07-02 16:58:21.028738 1w      +0.000113  1w      +0.000176  2w      +0.000483  1w            --           +0.002330  0w      +0.002382  0w
```

You can give a stream id, like `5`, and will see all requests with h2 stream number 5 from all sessions and processes. Or you give session and stream id, like `1-17`, which shows those in all processes. Or you give the full id, like `1733364-1-3`.

### Log Entries

If you prefer to see the log entries relevant (instead of the summary table), use `-l`:

```
> python3 src/h2wtf.py -l -S 1-3,5 error.log
[...time...] [pid:... tid:...] [http2:debug] [h2_stream.c(542)] AH03082: h2_stream(1-3,IDLE): created
[...time...] [pid:... tid:...] [http2:trace1] [h2_stream.c(583)] h2_stream(1-3,HALF_CLOSED_REMOTE): schedule GET https://localhost/styles.194b3660038d369a1ea7.css chunked=0
[...time...] [pid:... tid:...] [http2:trace1] [h2_task.c(626)] h2_task(2-3): process connection
[...time...] [pid:... tid:...] [http2:debug] [h2_stream.c(542)] AH03082: h2_stream(1-5,IDLE): created
[...time...] [pid:... tid:...] [http2:trace1] [h2_stream.c(583)] h2_stream(1-5,HALF_CLOSED_REMOTE): schedule GET https://localhost/runtime-es2015.a892664a65c0ae389f9a.js chunked=0
[...time...] [pid:... tid:...] [http2:trace1] [h2_task.c(626)] h2_task(2-5): process connection
[...time...] [pid:... tid:...] [http2:trace2] [h2_mplx.c(771)] h2_mplx(2-3): request done, 0.235000 ms elapsed
[...time...] [pid:... tid:...] [http2:trace2] [h2_mplx.c(771)] h2_mplx(2-5): request done, 0.320000 ms elapsed
[...time...] [pid:... tid:...] [http2:trace2] [h2_mplx.c(480)] h2_stream(1-3,CLEANUP): cleanup
[...time...] [pid:... tid:...] [http2:trace2] [h2_mplx.c(480)] h2_stream(1-5,CLEANUP): cleanup
[...time...] [pid:... tid:...] [http2:trace3] [h2_stream.c(574)] h2_stream(1-3,CLEANUP): destroy
[...time...] [pid:... tid:...] [http2:trace3] [h2_stream.c(574)] h2_stream(1-5,CLEANUP): destroy
```


### Frames

To also see the HTTP/2 frames sent/received for all or a subset of the requests, add `-f` to the options:

```
> python3 src/h2wtf.py -l -f -S 1-3 error.log
[...time...] [http2:debug] [h2_stream.c(542)] AH03082: h2_stream(1-3,IDLE): created
[...time...] [http2:debug] [h2_session.c(339)] AH03066: h2_session(1,BUSY,1): recv FRAME[HEADERS[length=95, hend=1, stream=3, eos=1]], frames=4/6 (r/s)
[...time...] [http2:trace1] [h2_stream.c(583)] h2_stream(1-3,HALF_CLOSED_REMOTE): schedule GET https://localhost/styles.194b3660038d369a1ea7.css chunked=0
[...time...] [http2:trace1] [h2_task.c(626)] h2_task(2-3): process connection
[...time...] [http2:trace2] [h2_mplx.c(771)] h2_mplx(2-3): request done, 0.235000 ms elapsed
[...time...] [http2:debug] [h2_session.c(591)] AH03068: h2_session(1,BUSY,4): sent FRAME[HEADERS[length=39, hend=1, stream=3, eos=0]], frames=8/7 (r/s)
[...time...] [http2:debug] [h2_session.c(591)] AH03068: h2_session(1,BUSY,4): sent FRAME[DATA[length=1291, flags=0, stream=3, padlen=0]], frames=8/8 (r/s)
[...time...] [http2:debug] [h2_session.c(591)] AH03068: h2_session(1,BUSY,4): sent FRAME[DATA[length=1291, flags=0, stream=3, padlen=0]], frames=8/9 (r/s)
[...time...] [http2:debug] [h2_session.c(591)] AH03068: h2_session(1,BUSY,4): sent FRAME[DATA[length=1291, flags=0, stream=3, padlen=0]], frames
...
```
