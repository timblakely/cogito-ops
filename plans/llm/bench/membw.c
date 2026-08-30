#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <pthread.h>
#include <sys/mman.h>
#include <time.h>
#include <sched.h>
#include <unistd.h>

static size_t BUF;          /* bytes */
static char  *buf;
static int    nthreads;
static int    mode;         /* 0 seq, 1 rand-block */
static size_t block = 6UL*1024*1024 + 400UL*1024;  /* ~6.4 MB expert block */
static double seconds = 4.0;
static int    pin = 0;
static int    cpulist[128]; static int ncpu = 0;

static double now(void){ struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec + 1e-9*t.tv_nsec; }

static volatile uint64_t sink;

typedef struct { int id; size_t bytes; } arg_t;

static uint64_t sumblock(const char *p, size_t n){
    const uint64_t *q = (const uint64_t*)p;
    size_t m = n/8;
    uint64_t a=0,b=0,c=0,d=0;
    size_t i=0;
    for(; i+4<=m; i+=4){ a+=q[i]; b+=q[i+1]; c+=q[i+2]; d+=q[i+3]; }
    for(; i<m; i++) a+=q[i];
    return a+b+c+d;
}

static void *worker(void *vp){
    arg_t *A = (arg_t*)vp;
    if (pin && ncpu) {
        cpu_set_t s; CPU_ZERO(&s); CPU_SET(cpulist[A->id % ncpu], &s);
        pthread_setaffinity_np(pthread_self(), sizeof(s), &s);
    }
    uint64_t acc=0; size_t done=0;
    unsigned int seed = 12345u + A->id*7919u;
    double t0 = now();
    if (mode==0){
        size_t chunk = BUF/nthreads;
        char *base = buf + (size_t)A->id*chunk;
        while (now()-t0 < seconds){ acc += sumblock(base, chunk); done += chunk; }
    } else {
        size_t nblocks = BUF/block;
        while (now()-t0 < seconds){
            for (int k=0;k<8;k++){
                size_t bi = (size_t)(rand_r(&seed)) % nblocks;
                acc += sumblock(buf + bi*block, block);
                done += block;
            }
        }
    }
    sink += acc;
    A->bytes = done;
    return NULL;
}

int main(int argc, char**argv){
    /* argv: sizeGB threads mode(seq|rand) hugepage(0|1) [cpulist] */
    double gb = atof(argv[1]);
    BUF = (size_t)(gb*1024.0*1024.0*1024.0);
    nthreads = atoi(argv[2]);
    mode = strcmp(argv[3],"rand")==0 ? 1 : 0;
    int huge = atoi(argv[4]);
    if (argc>6) seconds=atof(argv[6]);
    if (argc>5 && strlen(argv[5])){
        pin=1; char *s=strdup(argv[5]); char *tok=strtok(s,",");
        while(tok && ncpu<128){ cpulist[ncpu++]=atoi(tok); tok=strtok(NULL,","); }
    }
    BUF = (BUF/ (block*nthreads)) * (block*nthreads);
    buf = mmap(NULL, BUF, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS|MAP_NORESERVE, -1, 0);
    if (buf==MAP_FAILED){ perror("mmap"); return 1; }
#ifdef MADV_HUGEPAGE
    if (huge) madvise(buf, BUF, MADV_HUGEPAGE);
    else      madvise(buf, BUF, MADV_NOHUGEPAGE);
#endif
    /* fault in */
    for (size_t i=0;i<BUF;i+=4096) buf[i] = (char)(i>>12);
    /* report AnonHugePages after fault-in */
    double t0=now();
    pthread_t th[256]; arg_t A[256];
    for (int i=0;i<nthreads;i++){ A[i].id=i; A[i].bytes=0; pthread_create(&th[i],NULL,worker,&A[i]); }
    size_t tot=0;
    for (int i=0;i<nthreads;i++){ pthread_join(th[i],NULL); tot+=A[i].bytes; }
    double el=now()-t0;
    printf("mode=%s threads=%d huge=%d buf=%.1fGiB elapsed=%.2fs bytes=%.1fGiB BW=%.2f GB/s\n",
        mode?"rand":"seq", nthreads, huge, BUF/1073741824.0, el, tot/1073741824.0, tot/el/1e9);
    return 0;
}
