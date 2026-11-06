import pathlib, sys, unittest, threading
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'services'))
import core
class CoreTests(unittest.TestCase):
    def test_backpressure_multiple_segments(self):
        synth=core.Synth({'audio':{'max_inflight':2,'max_queued_bytes':4}})
        synth.segmenter.split=lambda _:['a','b','c','d']
        def run(job,voice,speed,sr,sem,sample_steps=None):
            try:
                for _ in range(10):job.push(b'1234')
            finally:
                with job.cond:job.done=True;job.cond.notify_all()
                sem.release()
        synth._run_job=run
        output=[]
        t=threading.Thread(target=lambda:output.append(b''.join(synth.stream('x'))),daemon=True);t.start();t.join(5)
        self.assertFalse(t.is_alive(),'backpressure deadlock');self.assertEqual(len(output[0]),160)
    def test_cancellation_drains_workers(self):
        synth=core.Synth({'audio':{'max_queued_bytes':4}});synth.segmenter.split=lambda _:['a','b','c']
        def run(job,voice,speed,sr,sem,sample_steps=None):
            try:
                for _ in range(100):job.push(b'1234')
            finally:
                with job.cond:job.done=True;job.cond.notify_all()
                sem.release()
        synth._run_job=run
        stream=synth.stream('x');next(stream);stream.close()
if __name__=='__main__':unittest.main()
