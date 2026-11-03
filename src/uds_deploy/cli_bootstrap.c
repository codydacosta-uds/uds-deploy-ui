/* Apache-2.0. Registered invocation entrypoint; never a deployment controller.
 * The original process execs the unchanged native binary with the original
 * argv, environment, stdin, process group and native exit/signal behavior.
 * Its output-only child receives ONLY channels allocated for this invocation.
 */
#define _GNU_SOURCE
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <limits.h>
#include <dirent.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif
extern char **environ;
static const unsigned char marker[]="UDSWATCH_ENTRY_V2";
__attribute__((used)) static const unsigned char registration_space[65536]="UDSWATCH_PLACEHOLDER_V2";
static int duplicate(int fd,int target){int result;do{result=dup2(fd,target);}while(result<0&&errno==EINTR);return result;}
static int highfd(int fd){if(fd>=3)return fd;int result=fcntl(fd,F_DUPFD,3);close(fd);return result;}
static int receive(int fd,int timeout,int *fds,int capacity,char *message,size_t size){
 struct pollfd ready={.fd=fd,.events=POLLIN};int result;
 do{result=poll(&ready,1,timeout);}while(result<0&&errno==EINTR);
 if(result<=0)return -1;
 char ancillary[CMSG_SPACE(sizeof(int)*4)];struct iovec vec={message,size};struct msghdr packet={0};
 memset(ancillary,0,sizeof(ancillary));memset(message,0,size);packet.msg_iov=&vec;packet.msg_iovlen=1;packet.msg_control=ancillary;packet.msg_controllen=sizeof(ancillary);
 ssize_t got=recvmsg(fd,&packet,0);if(got<=0)return -1;
 struct cmsghdr *rights=CMSG_FIRSTHDR(&packet);int count=0;
 if(rights&&rights->cmsg_level==SOL_SOCKET&&rights->cmsg_type==SCM_RIGHTS){count=(int)((rights->cmsg_len-CMSG_LEN(0))/sizeof(int));if(count>capacity)count=capacity;memcpy(fds,CMSG_DATA(rights),sizeof(int)*(size_t)count);}
 return count;
}
static int receive_path(int fd,char *path,size_t limit){
 for(size_t i=0;i<limit;i++){
  struct pollfd ready={fd,POLLIN,0};int result;
  do{result=poll(&ready,1,2500);}while(result<0&&errno==EINTR);
  if(result<=0||read(fd,path+i,1)!=1)return -1;
  if(!path[i])return 0;
 }
 return -1;
}
static int sendfds(int fd,char kind,int *fds,int count){
 char ancillary[CMSG_SPACE(sizeof(int)*2)];struct iovec vec={&kind,1};struct msghdr packet={0};
 memset(ancillary,0,sizeof(ancillary));packet.msg_iov=&vec;packet.msg_iovlen=1;
 if(count){packet.msg_control=ancillary;packet.msg_controllen=CMSG_SPACE(sizeof(int)*(size_t)count);struct cmsghdr *rights=CMSG_FIRSTHDR(&packet);rights->cmsg_level=SOL_SOCKET;rights->cmsg_type=SCM_RIGHTS;rights->cmsg_len=CMSG_LEN(sizeof(int)*(size_t)count);memcpy(CMSG_DATA(rights),fds,sizeof(int)*(size_t)count);}
 return sendmsg(fd,&packet,0)==1?0:-1;
}
static void broken_capture(const char *record){
 size_t length=strlen(record);if(length<=13||strcmp(record+length-13,"/capture.json"))return;
 char path[8192];if(length+1>sizeof(path))return;memcpy(path,record,length-13);strcpy(path+length-13,"/integrity");
 int fd=open(path,O_WRONLY|O_NOFOLLOW);struct stat st;
 if(fd>=0){
  if(!fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_uid==getuid()&&st.st_nlink==1){
   ssize_t marked;do{marked=pwrite(fd,"!",1,0);}while(marked<0&&errno==EINTR);
   if(marked!=1)unlink(record); /* An unmarkable capture is never advertised. */
  }
  close(fd);
 }
 if(!lstat(record,&st)&&S_ISREG(st.st_mode)&&st.st_uid==getuid())unlink(record);
}
/* Capture is a best-effort side channel. Only this native forwarding process
 * consumes native output. A Python crash/pause/full disk cannot lose bytes
 * already read here, block forwarding, or change the invocation's PID/status. */
static void capture_copy(int *copy,const char *record,const char *data,size_t size){
 if(*copy<0)return;
 unsigned char frame[32772];frame[0]=(unsigned char)size;frame[1]=(unsigned char)(size>>8);frame[2]=(unsigned char)(size>>16);frame[3]=(unsigned char)(size>>24);
 if(size)memcpy(frame+4,data,size);
 ssize_t sent;do{sent=send(*copy,frame,size+4,MSG_DONTWAIT);}while(sent<0&&errno==EINTR);
 if(sent!=(ssize_t)(size+4)){broken_capture(record);close(*copy);*copy=-1;}
}
static void drain(int *readers,int count,int copy,const char *record){
 struct pollfd files[3]={{readers[0],POLLIN,0},{count>1?readers[1]:-1,POLLIN,0},{copy,POLLIN,0}};
 int capacity=1048576;setsockopt(copy,SOL_SOCKET,SO_SNDBUF,&capacity,sizeof(capacity));
 int flags=fcntl(copy,F_GETFL);if(flags>=0)fcntl(copy,F_SETFL,flags|O_NONBLOCK);
 while(count){
  files[2].fd=copy;
  int result=poll(files,3,-1);if(result<0&&errno==EINTR)continue;if(result<0){broken_capture(record);break;}
  if(copy>=0&&files[2].revents){broken_capture(record);close(copy);copy=-1;}
  for(int i=0;i<2;i++)if(files[i].fd>=0&&files[i].revents){
   char data[32768];ssize_t size=read(files[i].fd,data,sizeof(data));
   if(size<0&&errno==EINTR)continue;
   if(size<=0){close(files[i].fd);files[i].fd=-1;count--;continue;}
   size_t offset=0;
   while(offset<(size_t)size){
    ssize_t written=write(i+1,data+offset,(size_t)size-offset);
    if(written<0&&errno==EINTR)continue;
    if(written<=0){/* Preserve downstream closure: stop holding the read end. */
     broken_capture(record);close(files[i].fd);files[i].fd=-1;count--;break;
    }
    offset+=(size_t)written;
   }
   capture_copy(&copy,record,data,(size_t)size);
  }
 }
 capture_copy(&copy,record,"",0);if(copy>=0)close(copy);
}
static void close_others(int first,int second){
 DIR *directory=opendir("/dev/fd");if(!directory)return;int own=dirfd(directory);struct dirent *entry;
 while((entry=readdir(directory))){char *end;long fd=strtol(entry->d_name,&end,10);if(*end||fd<0||fd>INT_MAX)continue;if(fd!=1&&fd!=2&&fd!=first&&fd!=second&&fd!=own)close((int)fd);}
 closedir(directory);
}
static void cleanup_capture(const char *record){
 size_t length=strlen(record);if(length<=13||strcmp(record+length-13,"/capture.json")||length>=8192)return;
 char path[8192];memcpy(path,record,length-13);path[length-13]=0;struct stat st;
 if(lstat(path,&st)||!S_ISDIR(st.st_mode)||st.st_uid!=getuid()||(st.st_mode&077))return;
 const char *names[]={"/capture.json","/ready.json","/console.log","/integrity"};
 for(int i=0;i<4;i++){strcpy(path+length-13,names[i]);unlink(path);}path[length-13]=0;rmdir(path);
}
static void stop_worker(pid_t worker){
 /* Only our optional capture child, never the native invocation. A stopped
  * child must not turn teardown into an unbounded wait on any platform. */
 kill(worker,SIGKILL);kill(worker,SIGCONT);
 for(int i=0;i<50;i++){if(waitpid(worker,NULL,WNOHANG)!=0)break;usleep(20000);}
}
static void guardian(int caller,char **fields,int argc,char **argv,pid_t native_pid){
 int pair[2];if(socketpair(AF_UNIX,SOCK_STREAM,0,pair)){close(caller);_exit(0);}
 pair[0]=highfd(pair[0]);pair[1]=highfd(pair[1]);pid_t worker=fork();
 if(worker<0){close(caller);close(pair[0]);close(pair[1]);_exit(0);}
 if(!worker){
  close(caller);close(pair[0]);char fdtext[32],pidtext[32];snprintf(fdtext,sizeof(fdtext),"%d",pair[1]);snprintf(pidtext,sizeof(pidtext),"%ld",(long)native_pid);
  char **args=calloc((size_t)argc+7,sizeof(char *));if(!args)_exit(125);
  args[0]=fields[2];args[1]="-IS";args[2]=fields[3];args[3]=fields[0];args[4]=fdtext;args[5]=pidtext;
  for(int i=0;i<argc;i++){args[i+6]=argv[i];}
  execve(fields[2],args,environ);_exit(125);
 }
 close(pair[1]);close_others(caller,pair[0]);
 /* The guardian is not a deployment process; hide the inherited verb from ps. */
 for(int i=1;i<argc;i++)argv[i][0]=0;
 int handles[4]={-1,-1,-1,-1};char message[8192];int count=receive(pair[0],2500,handles,4,message,1);
 int streams=message[0]=='1'?1:message[0]=='2'?2:0;
 if(count>0&&receive_path(pair[0],message+1,sizeof(message)-1))streams=0;
 if(!streams||count!=streams*2){sendfds(caller,'0',NULL,0);close(caller);close(pair[0]);stop_worker(worker);_exit(0);}
 int readers[2]={handles[0],-1},writers[2]={handles[1],-1};if(streams==2){readers[1]=handles[2];writers[1]=handles[3];}
 if(sendfds(caller,message[0],writers,streams)){close(caller);close(pair[0]);for(int i=0;i<count;i++)close(handles[i]);broken_capture(message+1);stop_worker(worker);cleanup_capture(message+1);_exit(0);}
 close(caller);for(int i=0;i<streams;i++)close(writers[i]);
 drain(readers,streams,pair[0],message+1);
 /* Native EOF belongs to the caller, not optional Python log teardown. */
 close(1);close(2);
 int status=0;pid_t done=0;
 for(int i=0;i<50&&done==0;i++){done=waitpid(worker,&status,WNOHANG);if(done==0)usleep(20000);}
 if(done==0){broken_capture(message+1);stop_worker(worker);}
 if(!WIFEXITED(status)||WEXITSTATUS(status)!=0)broken_capture(message+1);
 cleanup_capture(message+1);_exit(0);
}
int main(int argc,char **argv){
 char executable[PATH_MAX];
#ifdef __APPLE__
 uint32_t size=sizeof(executable);if(_NSGetExecutablePath(executable,&size))return 126;
#else
 ssize_t size=readlink("/proc/self/exe",executable,sizeof(executable)-1);if(size<0)return 126;executable[size]=0;
#endif
 int own=open(executable,O_RDONLY);if(own<0)return 126;
 struct stat info;if(fstat(own,&info)||info.st_size<=0||info.st_size>1024*1024){close(own);return 126;}
 size_t count=(size_t)info.st_size;unsigned char *data=malloc(count+1);if(!data){close(own);return 126;}
 size_t position=0;while(position<count){ssize_t n=read(own,data+position,count-position);if(n<0&&errno==EINTR)continue;if(n<=0){close(own);free(data);return 126;}position+=(size_t)n;}close(own);data[count]=0;
 size_t at=count;int found=0;char *fields[7];
 while(at){
  at--;
  if(at+sizeof(marker)-1+4+64>count||memcmp(data+at,marker,sizeof(marker)-1))continue;
  const unsigned char *length=data+at+sizeof(marker)-1;
  uint32_t n=(uint32_t)length[0]|((uint32_t)length[1]<<8)|((uint32_t)length[2]<<16)|((uint32_t)length[3]<<24);
  if(!n||n>65536||n>at)continue;
  unsigned char *start=data+at-n;size_t offset=0;int valid=1;
  for(int i=0;i<7;i++){if(offset>=n){valid=0;break;}fields[i]=(char *)start+offset;char *end=memchr(fields[i],0,n-offset);if(!end){valid=0;break;}offset=(size_t)((unsigned char *)end-start)+1;}
  if(valid&&offset==n&&fields[0][0]=='/'&&fields[1][0]=='/'&&(!strcmp(fields[5],"uds")||!strcmp(fields[5],"zarf"))){found=1;break;}
 }
 if(!found){free(data);return argc==2&&!strcmp(argv[1],"--uds-watch-bootstrap-probe-v1")?0:126;}
 /* entry, native, python, bootstrap, package, tool, owner UID */
 const char *native=fields[1];int control[2]={-1,-1};
 if(getuid()!=(uid_t)strtoul(fields[6],NULL,10)||access(fields[2],X_OK)||access(fields[3],R_OK)||access(fields[4],R_OK))goto native_exec;
 if(socketpair(AF_UNIX,SOCK_STREAM,0,control))goto native_exec;
 control[0]=highfd(control[0]);control[1]=highfd(control[1]);
 if(control[0]<0||control[1]<0)goto native_exec;
 pid_t native_pid=getpid();pid_t helper=fork();
 if(helper<0)goto native_exec;
 if(!helper){
  close(control[0]);signal(SIGINT,SIG_IGN);signal(SIGQUIT,SIG_IGN);signal(SIGTERM,SIG_IGN);signal(SIGPIPE,SIG_IGN);
  guardian(control[1],fields,argc,argv,native_pid);
 }
 close(control[1]);control[1]=-1;
 int fds[2]={-1,-1};char message[2];int received=receive(control[0],3000,fds,2,message,sizeof(message));
 int expected=message[0]=='1'?1:message[0]=='2'?2:0;
 if(expected&&received==expected){
  int saved[2]={fcntl(1,F_DUPFD_CLOEXEC,3),fcntl(2,F_DUPFD_CLOEXEC,3)};
  if(saved[0]>=0&&saved[1]>=0){
   if(duplicate(fds[0],1)<0||duplicate(fds[expected==1?0:1],2)<0){duplicate(saved[0],1);duplicate(saved[1],2);}
  }
  for(int i=0;i<2;i++)if(saved[i]>=0)close(saved[i]);
 }
 for(int i=0;i<received;i++)close(fds[i]);
native_exec:
 if(control[0]>=0){close(control[0]);}
 if(control[1]>=0){close(control[1]);}
 execve(native,argv,environ);int saved=errno;perror("native CLI");free(data);return saved==ENOENT?127:126;
}
