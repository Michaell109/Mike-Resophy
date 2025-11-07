# ChatRex: Taming Multimodal LLM for Joint Perception and Understanding

Qing Jiang \(^{1,2}\) , Gen Luo \(^{1}\) , Yuqin Yang \(^{1,2}\) , Yuda Xiong \(^{1}\) , Zhaoyang Zeng \(^{1}\) , Yihao Chen \(^{1}\) , Tianhe Ren \(^{1}\) , Lei Zhang \(^{1,2\dagger}\)

\(^{1}\) International Digital Economy Academy (IDEA)

\(^{2}\) South China University of Technology

mountchicken@outlook.com，leizhang@idea.edu.cn

## Abstract

Perception and understanding are two pillars of computer vision. While multimodal large language models (MLLM) have demonstrated remarkable visual understanding capabilities, they arguably lack accurate perception abilities, e.g. the stage-of-the-art model Qwen2-VL only achieves a 43.9 recall rate on the COCO dataset, limiting many tasks requiring the combination of perception and understanding. In this work, we aim to bridge this perception gap from both model designing and data development perspectives. We first introduce ChatRex, an MLLM with a decoupled perception design. Instead of having the LLM directly predict box coordinates, we feed the output boxes from a universal proposal network into the LLM, allowing it to output the corresponding box indices to represent its detection results, turning the regression task into a retrieval-based task that LLM handles more proficiently. From the data perspective, we build a fully automated data engine and construct the Rexverse-2M dataset which possesses multiple granularities to support the joint training of perception and understanding. After a three-stage training approach, ChatRex demonstrates strong perception and understanding performance, and the combination of these two capabilities also unlocks many attractive applications, demonstrating their complementary roles in MLLM. Code is available at https://github.com/IDEA-Research/ ChatRex.

# 1. Introduction

Perception and understanding are two fundamental human faculties within behavioral science. Humans initially perceive objects, with vision signals transmitted to the brain for understanding, and can then locate back to the objects during conversation. In pursuit of AGI, Multimodal Large

Language Models (MLLMs) [3, 4, 6, 13, 14, 16, 18, 36, 60, 64, 79, 85] have exhibited remarkable capacities for visual understanding empowered by advancements in Large Language Models (LLMs) [1, 2, 5, 15, 22, 78, 80, 83, 84]. Despite showing strong visual understanding, we find through experiments that these models generally lack fine-grained perception capabilities, particularly in object detection.

We evaluate the performance of several general-purpose [14, 85] and detection-focused [10, 61, 94] MLLMs on the COCO [46] dataset by prompting them to detect objects within the image. The state-of-the-art model Qwen2-VL-7B [85] only achieves a 43.9 recall rate at an IoU threshold of 0.5. The results indicate that MLLMs still struggle with fundamental perception tasks despite their remarkable visual understanding capabilities. This shortfall in perception constrains them in numerous tasks requiring precise perception, such as autonomous driving and robotic navigation. Also, it hinders their interactivity by identifying objects during conversation. We argue that this performance gap between perception and understanding in MLLMs arises primarily from two factors:  \(i\)  modeling conflicts between these two tasks, and  \(ii\)  lack of data that seamlessly balances both perception and understanding.

For object detection, a common practice is to quantify [12] box coordinates into tokens within the vocabulary of LLM to fit the auto-regressive framework. Although this ensures compatibility with understanding tasks through next-token prediction, we argue this method is in conflict with accurately modeling perception for three reasons:  \(i\)  Error propagation: representing a single box typically requires 9 tokens including digits, square brackets, and commas, where an error in any token can cause cascading errors, which become even worse in multi-object detection. In subsequent experiments, we find that this is one of the reasons for the low recall rate;  \(ii\)  Ambiguity in prediction order: there is no inherent order among objects in object perception, yet the auto-regressive nature imposes a sequential order that the LLM must decide which object to predict first and  \(iii\)  Quantization range limitation: quantization er

## Grounding & Detection

Q: Please detect bottle, knife fork ...  
A: <g> bottle </g> <o> <obj12> </o> ...

![](images/8b1b42cfcc5f074341a3f5654797bb991f2def641f236cea1fdc17837bae7ab6.jpg)

![](images/97c228a9150ee283d7e41c886b85e3731edc4d6f7fab6a34a66279fdbe67067d.jpg)

### Grounded Counting

Q How many dogs are there?  
A: There are 20  \(<g> dogs</g><o><obj6...</o>\)

![](images/7afba451cb24e8c71b4af2810013aa848d522e2b2db1703906407ea4bf4b5ba6.jpg)

### Referring

Q: Please detect man with a green hat...  
A: <g>man with a green hat</g><0><obj4>...</o>

![](images/db7f8e6bff20bf009c7bf69aa1568976aa3dd6bf517c3172b0574c3b87e4c876.jpg)

### Grounded Conversation

Answer the question in grounded format. What is unusual about this image?

The unusual aspect of this image is that it features  \(<g>dog</g><o><obj3>.<o>s\)  and a  \(<g>cupcake <g>0><obj0>\ldots <o\succ s\)  which is not a common sight. Typically, images of dogs are not associated with food items like cupcakes. The combination of a dog and a cupcake in the same image is unexpected and creates a unique and intriguing visual experience.

![](images/6904d86ebd1174e8bcdfc5596637ac27939f0f5a09d6175c56cf287b7dff5786.jpg)

### Grounded Image Caption

Provide a short description of the image and ground the objects that are mentioned.

A: A <g> young woman </g> <o> <obj5>/<o> with </g> long brown hair</g> <o> <obj7>/<o> is lying on her back, wearing a <g> white t-shirt </g> <obj11>/<o> and <g> blue jeans </g> <o> <obj2>/<o>, with </g> her hand </g> <obj1<o> gently touching </g> her head </g> <obj7>/<o>

![](images/6fb4a431cb8d2a95697e8991da9a2342a7de92c994d6aee38b0ca0e5818bf577.jpg)

### Region Description

Provide one-sentence descriptions for  \(<\mathrm{ob}1>\)  and  \(<\mathrm{ob}1>\) , respectively.

A:  \(<g>\)  A majestic lion statue, intricately carved and adorned with a crown, stands proudly on a pedestal, exuding strength and regality  \(\langle g\rangle < 0 > <   o j o ] <   / o >\) \(<  g>\)  A majestic bronze statue of a mounted figure, adorned with a crown and holding a sword, stands proudly on a pedestal, surrounded by a group of people  \(\langle g\rangle < 0 > <   o b j > <   / o >\)

![](images/9ab6e86d860bf4ff80f7f5ce2e732a08c8e54a512b6ad39306914fe5fbe39c11.jpg)  
Figure 1. Overview of the perception capabilities in ChatRex. We utilize a decoupled design for perception and understanding, allowing ChatRex to respond to questions while simultaneously grounding its answers to the referenced objects.

### Region QA

Q: what might be the species of  \(<\mathrm{obj}0>\)

A The species of  \(<\mathrm{obj}>\)  appears to be a dog, likely a breed with black and white fur, such as a Border Collie or a similar herding dog.

![](images/d230d8cc440512e338ec9a506898cf67bb77b5f7a62efd7bcd3508854c431b59.jpg)

### Region Relationships

What is  \(<\mathrm{obj}>0\)  and  \(<\mathrm{obj}1>\)  hodling respectively? And what might be their relationship.

\(\underline{\underline{A}} < \underline{\underline{o}b}\underline{\underline{0}}\underline{\underline{j}} >\)  is holding a toy gun, while  \(\langle \text{obj} \rangle\)  is holding a toy balloon. They are standing next to each other, which suggests they might be companions or partners.

![](images/49957410592bd15a4e678d95c3fc8b948425c15beaa773b5d4e3e7c973b789e7.jpg)

ror easily occurs when the image size is large.

To address these inherent modeling conflicts, we adopt a decoupled model design and introduce ChatRex. For multimodal understanding tasks like image caption and image QA, we retain the auto-regressive text prediction framework. However, for perception, particularly object detection, we transform the task as a retrieval-based task inspired by Groma [61]. Specifically, instead of prompting the LLM to predict bounding box coordinates, the boxes are directly provided as inputs, each represented as an object token by combining its RoI feature with its positional embedding. When the LLM needs to reference an object, it outputs the index of the relevant box. This method represents each box as a single token without quantization, with the sequence order determined by the input boxes, effectively addressing prior modeling conflicts.

However, this retrieval-based approach presents two key challenges for achieving optimal performance: the need for high-resolution visual input and a robust object proposal model. To address the first challenge, we adopt a dual

vision encoder design to incorporate additional vision encoder [56] to provide high-resolution visual information for perception. For the second, we introduce a Universal Proposal Network (UPN), which leverages granularity-based prompt learning on a pre-trained open-set object detection model. This enables the generation of proposals that cover diverse granularities, categories, and domains, thereby ensuring robust box inputs for the LLM.

From the data perspective, current MLLMs are also limited by the lack of data that effectively balances both perception and understanding. To address this limitation, we developed a fully automated data engine to construct the Rexverse-2M dataset, which comprises image-region-text annotation triplets at varying levels of granularity. The data engine is composed of three primary modules. The first module generates image captions for input images [14], while the second aligns referenced objects or phrases using a grounding model [71]. The third module [22] refines region descriptions at multiple granularities.

Experimental results show that ChatRex achieves

strong performance in object detection tasks, including COCO[46], LVIS[25], and RefCOCO+/g [30, 62, 95], while also demonstrating competitive performance on multimodal benchmarks. Our findings highlight that both perception and understanding are fundamental capabilities for multimodal models, and their integration leads to performance gain with expansion on the scope of real-world applications, as illustrated in Fig. 1. To summarize, our contributions are threefold:

- We reveal the performance gap in the perception of MLLMs and introduce a decoupled model ChatRex and a universal proposal network (UPN) to address the modeling conflict between perception and understanding.  
- We develop an automated data engine to create Rexverse2M, a comprehensive dataset supporting both perception and understanding tasks for model training.  
- Experimental results demonstrate that ChatRex exhibits strong perception and multimodal understanding capabilities, highlighting that these two complementary abilities are both essential for MLLM.

# 2. Related Work

## 2.1. General MLLMs

Leveraging breakthroughs in large language models within natural language processing, Multimodal Large Language Models (MLLMs) [3, 4, 6, 13, 14, 16, 18, 36, 60, 64, 79, 85] have demonstrated robust visual understanding capabilities. LLaVA [50] pioneered the paradigm of visual instruction tuning, inspiring a wave of subsequent work. Research on general-purpose MLLMs encompasses various directions, including:  \(i\)  exploring the use of high-resolution image inputs to enhance model perceptual abilities, with models like LLaVA-Next [51], SPHINX [48], Monkey [43], InternLM-XComposer2 [20], LLaVA-UHD [89], NVLM [17] employing image slicing methods, and others like LLaVA-HR [59], Mini-Gemini [41], Eagle [76], and MG-LLaVA [108] utilizing high-resolution vision encoders for additional vision encoding;  \(ii\)  investigating diverse approaches for pre-training [45, 63, 91] and fine-tuning data [37, 82], and  \(iii\)  extending to multi image [28, 37] or video tasks [44, 90].

## 2.2. Perception MLLMs

While generic multimodal models demonstrate strong image-level understanding, they still lack fine-grained perception capabilities. Inspired by Pix2seq [12], several works such as Kosmos-2 [65], Shikra [10], Ferret [94, 104], CogVLM [86], Griffon [100, 101] and other generalized MLLMs [14, 63, 85] have transformed box regression into a quantized coordinate prediction task suited for LLM next-token prediction. SoM [93] uses a set of marks to prompt GPT4V for visual grounding tasks. Another research di

![](images/75f24d27008efc81dc8589a39318b4d5ea88dae1e7778c890390027d577c9ce8.jpg)  
Figure 2. Overview structure of the Universal Proposal Network (UPN). UPN is a DETR-based model capable of detecting any object at two granularities.

rection employs additional decoders for perception. For instance, LISA [34], GLaMM [69], LLaVA-Grounding [105], PerceptionGPT [66], and VisionLLMv2 [87] use auxiliary detection or segmentation models for perception tasks. Groma [61] initially proposed re-framing detection as a box retrieval task, and we follow this method in this work.

# 3. ChatRex Architecture

ChatRex employs a design that decouples perception from understanding. For perception, we train a universal proposal network to detect arbitrary objects, supplying box inputs to the LLM. For understanding, we adopt the standard LLaVA [50] structure with a dual vision encoder to facilitate high-resolution image encoding. We introduce each part in the following sections.

## 3.1. Universal Proposal Network (UPN)

To ensure that the LLM can accurately retrieve the correct box, it is essential that the input boxes comprehensively encompass all objects within an image. This requires a proposal model with two key properties:  \(i\)  robust generalization ability to generate proposal boxes for any object in any scenario, and  \(ii\)  the proposed boxes should be comprehensive, including both instance-level and part-level objects.

To meet these requirements, a straightforward approach is to aggregate multiple detection datasets, merge their categories, and treat all object classes as a single foreground category for training. However, this strategy is suboptimal due to inconsistencies in object definitions across different datasets. For example, while datasets such as COCO [46] and O365 [75] annotate objects at the instance level, SA1B [32] annotate objects at part-level. These discrepancies in labeling can introduce ambiguities that compromise training stability. To mitigate this issue, we adopt a dual-granularity prompt tuning strategy.

Specifically, we utilize T-Rex2 [29] as our base model. T-Rex2 is a DETR-based [8] model trained on vast data and exhibits strong generalization, making it a suitable pretrained model for detecting any objects in varied scenes.

![](images/79f3c765f68b69f4b2ed0cf991672f2fed052f484b278ee25600a96a75f9d053.jpg)  
Figure 3. Overview of the proposed ChatRex model architecture and the workflow for modeling the detection output of the LLM from coordinates prediction task to input box indices retrieval task.

The model outputs object queries  \(\mathbf{Q}_{\mathrm{dec}}\)  that pass through an MLP to predict bounding boxes. The classification of these bounding boxes is achieved via a dot product between the queries and the prompt embeddings  \(\mathbf{E}\) :

\[
\mathbf {S} _ {\mathrm {c l s}} = \mathbf {E} \cdot \mathbf {Q} _ {\mathrm {d e c}} ^ {T}: \mathbb {R} ^ {C \times D} \times \mathbb {R} ^ {D \times N} \rightarrow \mathbb {R} ^ {C \times N} \tag {1}
\]

Where  \(C\)  is the number of classes,  \(N\)  represents the number of detection queries (default is 900), and  \(D\)  is the channel dimension of outputted queries. We extend T-Rex2 by introducing two additional learnable prompts,  \(\mathbf{P}_{\mathrm{fine}}\)  and  \(\mathbf{P}_{\mathrm{coarse}}\) , concatenated into  \(\mathbf{P}_{\mathrm{concat}}\)  to classify boxes into fine-grained or coarse-grained categories:

\[
\mathbf {S} _ {\mathrm {c l s}} = \mathbf {P} _ {\text {c o n c a t}} \cdot \mathbf {Q} _ {\mathrm {d e c}} ^ {T}: \mathbb {R} ^ {2 \times D} \times \mathbb {R} ^ {D \times N} \rightarrow \mathbb {R} ^ {2 \times N} \tag {2}
\]

For training, we utilize SA-1B as the fine-grained dataset and other detection datasets (such as COCO and O365) as coarse-grained inputs. This dual-granularity prompt design effectively resolves labeling ambiguities between datasets, allowing the proposal model to accurately capture and characterize objects across varying levels of detail.

## 3.2.MLLM Architecture

Dual Vision Encoders. An accurate perception system typically requires high-resolution inputs. To equip ChatRex with sufficient perception capabilities, we adopt an additional high-resolution vision encoder for image encoding. As illustrated in Fig. 3, we use the ViT [21] from CLIP [67] for low-resolution image encoding and ConvNeXt [56] from LAION [73] for high-resolution image encoding. To reduce the number of vision tokens fed into the LLM, we first adjust the input resolutions for both vision encoders to ensure they generate the same number of tokens at the last scale. We then directly concatenate these two tokens

along the channel dimension, producing the same number of the low-resolution token count.

Object Encoder. We encode each output box from the universal proposal network to object tokens and feed them to the LLM. Assume  \(K\)  input boxes  \(\{B_i\}_{i=1}^K\)  from the UPN, let  \(\mathcal{F}_{\mathrm{H}}\)  denote the multi-scale visual features produced by the high-resolution encoder, for each box  \(B_i\) , we extract its content feature  \(\mathcal{C}_i\)  using multi-scale RoI Align [26]:

\[
\mathcal {C} _ {i} = \operatorname {R o I A l i g n} \left(\mathcal {F} _ {\mathrm {H}}, B _ {i}\right) \tag {3}
\]

Since the RoI feature does not contain positional information which is essential for referring tasks, we enhance each object feature with a positional embedding to capture spatial context. We encode each box coordinate through a sin-cos position embedding layer and add to the RoI feature:

\[
\mathcal {V} _ {i} = \mathcal {C} _ {i} + \operatorname {P E} \left(B _ {i}\right) \tag {4}
\]

LLM. We use two separate MLP projectors to map visual and object tokens to the text space. We also add an index token to each object token to inform the LLM about the index of each object token, which will be described in Sec. 3.3. These tokens are then concatenated with the text token and fed into the LLM for the next-token prediction task. We use Qwen2.5-7B [92] as our default LLM.

## 3.3. Task Formulations

We formulate the task of leveraging LLM for detection as an index selection process over input boxes. To do so, we first extend the vocabulary of LLM by incorporating specialized tokens, including object index tokens  \(<\mathsf{obj}0>\) ,  \(<\mathsf{obj}1>\) , ...,  \(<\mathsf{obj}N>\) , where  \(N\)  denotes the maximum number of input boxes and is set to 100 in this work; grounding start

![](images/91e9515a2e14a02ae34b480e787f72cc10c08c0fd9257c5b04bf3a1633d90d49.jpg)  
Figure 4. Overview of the ChatRex data engine. There are three main components, including the image captioning module, the grounding module, and the region captioning module.

token  \(< \mathfrak{g}>\) ; grounding end token  \(< / \mathfrak{g}>\) ; object start token  \(< \circ>\) ; and object end token  \(< / \circ>\) .

LLM Input Format. The input token sequence for the LLM are structured as follows:

<image>\n<obj1><roi>...<objN><roi>\nQuestion

where  \(<\text{image}>\)  represents the visual tokens from the vision encoder, and  \(<\text{roi}>\)  denotes the object feature associated with each corresponding bounding box. Each  \(<\text{roi}>\)  token is prefixed by its respective object index token.

Decoupled Task Formulations. The detection results produced by the LLM are structured using the following combination of noun phrases and box indices:

\(<  g>\)  noun phrases  \(<  / g><  o><  \text{objm} >...\)  ..<objn><o>

where  \(\langle \text{objm} \rangle\)  and  \(\langle \text{objn} \rangle\)  refer to specific object index tokens, identifying the start  \((m)\)  and end  \((n)\)  of the sequence of detected objects linked to the noun phrases. This structured format enables a precise mapping between noun phrases and their corresponding bounding box indices.

With this input-output schema, ChatRex can handle various tasks such as detection, grounding, region comprehension, and grounded dialogue, in addition to generating plain text responses, as illustrated in Fig. 3.

# 4. Data and Training

To equip ChatRex with robust perception and understanding capabilities, we build RexVerse-2M dataset with two million annotated images, featuring multi-granularity annotations generated through a fully automatic data engine.

We then adopt a standard two-stage training methodology following LLaVA [50], enabling the model to preserve its perception capabilities while progressively acquiring multimodal understanding and dialog skills.

## 4.1. RexVerse-2M Data Engine

Our objective is to construct a dataset that can be effectively utilized for both perception and understanding tasks. To achieve this, our data pipeline focuses on generating an annotation triplet comprising image descriptions, region descriptions, and bounding boxes. As shown in Fig. 4, the data engine is structured around three core modules: image captioning, object grounding, and region captioning.

Image Collection. We started by collecting images from COYO700M [7] dataset through a series of filtering processes including removing images with small resolution and NSFW tags. We also train an image classifier to filter out low-content web images with plain white backgrounds. Finally, we selected two million images as the dataset images.

Image Caption. We use InternVL2-8B [14] to generate image caption for each image. This image caption will refer to the main objects in the image by their category name or descriptive phrases.

Phrase Grounding. We then utilize SpaCy to extract noun phrases from generated image captions. Depending on the caption, SpaCy may identify category names, such as soldier or descriptive phrases (at least 3 words per region) like military-style uniform. We will also filter out some abstract nouns that might not be an object

like image, background etc. Subsequently, we employ Grounding DINO 1.5 [71] to ground the filtered noun phrases. This process ultimately produces boxes associated with their category names or short phrase descriptions.

Phrase-Conditioned Region Caption. To support the training for understanding tasks, it is essential to generate detailed descriptions for each region rather than relying solely on category names or short phrases, which often provide limited information. A straightforward approach might involve cropping each region and feeding it into an MLLM model for image captioning. However, this method is prone to hallucinations when the cropped regions are too small or contain parts of other objects. To reduce such inaccuracies, we implemented a phrase-conditioned image description strategy. Specifically, we leverage the InternVL2-8B model [14] to generate image captions that are conditioned on predefined phrases related to each region. By guiding the model with these phrases, we ensure that the generated descriptions are more accurate and context-relevant, significantly reducing the likelihood of hallucinations and enhancing the quality of the region-specific captions.

Region Caption Filtering and Rewriting. Lastly, we employ LLaMA3-8B [22] to verify whether the generated captions accurately align with their original category names or short phrases, filtering out any remaining hallucinated outputs. Once validated, we then prompt it to refine these detailed captions into more concise referring expressions, thereby enhancing training for referring tasks.

Rexverse-2M consists of 2.1 million images with captions, 10.2 million regions annotated with category labels, 2.5 million regions labeled with short phrases, 2.5 million regions with detailed descriptions, and 2.4 million regions with referring descriptions. Additionally, we use this data engine to annotate 776K grounded conversation data from the ALLaVA-4V-Instruct [9] dataset for instruction tuning. Specifically, the conversation responses are treated as image captions, which are then passed through the engine.

## 4.2. Training

UPN Training. We utilize two types of datasets with bounding boxes to train our UPN: coarse-grained datasets including O365 [75], OpenImages [33], Bamboo [107], COCO [46], LVIS [25], HierText [57], CrowdHuman [74], SROIE [27] and EgoObjects [109]; and fine-grained datasets SA-1B [32]. All dataset categories are defined as either coarse-grained or fine-grained, reducing the task to a binary classification problem. Following T-Rex2, Hungarian matching is used to match predictions with ground truth. We employ L1 Loss and GIOU Loss for box predictions, along with sigmoid focal loss for classification.

ChatRex Training Tasks. We adopt three main tasks to train ChatRex including  \(i\) ) Grounding: where the model outputs the indices of corresponding objects based on a given

<table><tr><td>Stage</td><td>Task</td><td># Samples</td><td>Datasets</td></tr><tr><td>Stage1</td><td>Image Caption</td><td>976K</td><td>ALLAVA-4V-Caption [9]</td></tr><tr><td>Stage2</td><td>Grounding &amp; Region Understanding</td><td>2.07M</td><td>COCO [46], O365 [75], LVIS [25], RefCOCO/+g [30, 62, 95], Rexverse-2M</td></tr><tr><td>Stage3</td><td>Grounding &amp; Counting &amp; Region Understanding &amp; Grounded Conversation Conversation &amp; QA</td><td>3.8M</td><td>Reverser-2M, COCO, O365, LVIS, RefCOCO/+g [30, 62, 95], PACO [68], MVDP [47], Osprey [97], CrowdHuman [74], VCR [99], ALLAVA-4V-Instruct [9], LLAVA-1.5 [49], LLaVA-Onevision [37]</td></tr></table>

Table 1. Training data and tasks for each stage.

category name, phrase, or referring expression. ii) Region Understanding: where, given region indices, the model generates descriptions at varying levels of detail, including category names, short phrases, detailed descriptions, or referring descriptions, and iii) Grounded Image Conversation: The model needs to output indices of objects mentioned in its generated conversation output. We mix the ground truth boxes of the current image with the proposal boxes from UPN, and keep at most 100 boxes as input. We adopt a three-stage training process and the data for each stage are listed in Tab. 1

Stage-1: Alignment Training. In the first stage, the objective is to align visual features and object features with the text feature space. To achieve this, we train the image projection MLP, object projection MLP, as well as the input and output embeddings of the LLM, given that we have added special tokens to its vocabulary.

Stage-2: Perception Training. In this stage, we improve the perception capability of ChatRex by training it on Rexverse-2M and other grounding data. All the parameters are trainable in this stage.

Stage-3: Joint Training. In this stage, we integrate perception and understanding tasks into a unified training process, ensuring that ChatRex acquires both capabilities. This joint optimization equips the model with comprehensive multimodal abilities and enables mutual enhancement between perception and understanding.

# 5. Experiments

## 5.1. Perception Capability Evaluation

Evaluation Metrics. Mean Average Precision (mAP) [46] is a common metric for object detection, which measures the area under the precision-recall curve, reflecting both the precision and recall of the model. However, for MLLMs that predict coordinates as vocabulary tokens, computing AP can be challenging due to the lack of confidence scores for each predicted box. Therefore, we directly report recall and precision metrics instead. We provide all ground truth categories for the current test image and prompt the model to generate the corresponding coordinate boxes. The details of prompts used for each model are included in the Appendix. For ChatRex, we use fine-grained proposal boxes from UPN and their corresponding confidence scores as input, enabling us to compute precision, recall, and mAP.

<table><tr><td>Method</td><td>Type</td><td colspan="3">COCO-Val</td><td colspan="6">LVIS-Mini Val</td><td colspan="3">RefCOCO</td><td colspan="3">RefCOCO+</td><td colspan="2">RefCOCOg</td></tr><tr><td></td><td></td><td>P@0.5</td><td>R@0.5</td><td>mAP</td><td>P@0.5</td><td>R@0.5</td><td>mAP</td><td>AP-R</td><td>AP-C</td><td>AP-F</td><td>val</td><td>testA</td><td>testB</td><td>val</td><td>testA</td><td>testB</td><td>val</td><td>test</td></tr><tr><td>Faster-RCNN [70]</td><td rowspan="4">Closed-set Detection Model</td><td>-</td><td>-</td><td>42.0</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr><tr><td>DETR [8]</td><td>-</td><td>-</td><td>43.3</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr><tr><td>Pix2Seq [12]</td><td>-</td><td>-</td><td>43.2</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr><tr><td>DINO [102]</td><td>-</td><td>-</td><td>49.4</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr><tr><td>Florence2 [88]</td><td rowspan="4">Open-set Detection Model</td><td>-</td><td>-</td><td>43.4</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr><tr><td>GLIP [39]</td><td>-</td><td>-</td><td>49.8</td><td>-</td><td>-</td><td>37.3</td><td>28.2</td><td>34.3</td><td>41.5</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr><tr><td>T-Rex2 [29]</td><td>-</td><td>-</td><td>46.5</td><td>-</td><td>-</td><td>47.6</td><td>45.4</td><td>46.0</td><td>49.5</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr><tr><td>Grounding DINO [52]</td><td>-</td><td>-</td><td>48.4</td><td>-</td><td>-</td><td>33.0</td><td>22.2</td><td>30.7</td><td>38.8</td><td>89.2</td><td>91.9</td><td>86.0</td><td>81.1</td><td>87.4</td><td>74.7</td><td>84.2</td><td>84.9</td></tr><tr><td>Shikra-7B [10]</td><td rowspan="5">MLLM</td><td>40.3</td><td>21.5</td><td>-</td><td>52.8</td><td>14.5</td><td>-</td><td>-</td><td>-</td><td>-</td><td>87.0</td><td>90.6</td><td>80.2</td><td>81.6</td><td>87.4</td><td>72.1</td><td>82.3</td><td>82.2</td></tr><tr><td>Ferret-7B [94]</td><td>66.3</td><td>33.5</td><td>-</td><td>72.9</td><td>25.2</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr><tr><td>Groma-7B [61]</td><td>69.9</td><td>28.9</td><td>-</td><td>76.3</td><td>10.9</td><td>-</td><td>-</td><td>-</td><td>-</td><td>89.5</td><td>92.1</td><td>86.3</td><td>83.9</td><td>88.9</td><td>78.1</td><td>86.4</td><td>87.0</td></tr><tr><td>InternVL2-7B [14]</td><td>45.3</td><td>24.5</td><td>-</td><td>51.6</td><td>13.1</td><td>-</td><td>-</td><td>-</td><td>-</td><td>87.1</td><td>91.1</td><td>80.7</td><td>79.8</td><td>87.9</td><td>71.4</td><td>82.7</td><td>82.7</td></tr><tr><td>Qwen2-VL-7B [85]</td><td>59.3</td><td>43.9</td><td>-</td><td>77.0</td><td>34.7</td><td>-</td><td>-</td><td>-</td><td>-</td><td>91.7</td><td>93.6</td><td>87.3</td><td>85.8</td><td>90.5</td><td>79.5</td><td>87.3</td><td>87.8</td></tr><tr><td>ChatRex-7B</td><td></td><td>73.5</td><td>72.8</td><td>48.2</td><td>80.3</td><td>58.9</td><td>42.6</td><td>44.6</td><td>48.4</td><td>37.2</td><td>91.0</td><td>94.1</td><td>87.0</td><td>89.8</td><td>91.9</td><td>79.3</td><td>89.8</td><td>90.0</td></tr></table>

Table 2. Comparison of different models on object detection tasks on the COCO, LVIS, and RefCOCO+/g datasets. For COCO and LVIS, we report the R@0.5 and P@0.5 metrics for MLLMs, representing recall and precision at an IoU threshold of 0.5, respectively. For RefCOCO+/g, a prediction is considered correct if its overlap IoU with the ground truth is larger than 0.5.  

<table><tr><td>Model</td><td>MME</td><td>MMB</td><td>SEED1</td><td>MMStar</td><td>MMVet</td><td>MMMU</td><td>AI2D</td><td>OCRbench</td><td>TextVQA</td><td>POPE</td><td>Hallusion</td></tr><tr><td>BLIP-2 [38]</td><td>1293.8</td><td>-</td><td>49.7</td><td>-</td><td>22.4</td><td>-</td><td>-</td><td>-</td><td>-</td><td>85.3</td><td>-</td></tr><tr><td>InstructBLIP [16]</td><td>1212.8</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>78.9</td><td>-</td></tr><tr><td>Mini-Gemini-HD-8B [42]</td><td>1606.0</td><td>72.7</td><td>73.2</td><td>-</td><td>-</td><td>37.3</td><td>73.5</td><td>47.7</td><td>70.2</td><td>-</td><td>-</td></tr><tr><td>LLaVA-HR [58]</td><td>1554.0</td><td>-</td><td>64.2</td><td>-</td><td>31.2</td><td>-</td><td>-</td><td>-</td><td>67.1</td><td>87.6</td><td>-</td></tr><tr><td>LLaVA-NeXT-7B [51]</td><td>1498.0</td><td>68.7</td><td>72.2</td><td>38.4</td><td>42.2</td><td>35.3</td><td>69.0</td><td>531</td><td>64.6</td><td>86.7</td><td>29.1</td></tr><tr><td>Eagle-X5-7B [76]</td><td>1579.0</td><td>68.8</td><td>73.5</td><td>41.7</td><td>42.6</td><td>36.3</td><td>77.2</td><td>574</td><td>71.2</td><td>88.8</td><td>37.8</td></tr><tr><td>MM1.5-7B [103]</td><td>1514.9</td><td>-</td><td>73.4</td><td>-</td><td>42.2</td><td>41.8</td><td>72.2</td><td>635</td><td>76.5</td><td>88.6</td><td>-</td></tr><tr><td>Cambrian-8B [81]</td><td>1547.1</td><td>75.9</td><td>74.7</td><td>47.1</td><td>48.9</td><td>41.6</td><td>73.6</td><td>610</td><td>71.7</td><td>86.8</td><td>39.4</td></tr><tr><td>LLaVA-OV-7B [37]</td><td>1577.8</td><td>83.2</td><td>76.7</td><td>61.9</td><td>51.9</td><td>47.9</td><td>82.4</td><td>622</td><td>78.5</td><td>88.4</td><td>31.6</td></tr><tr><td>InternVL2-8B [14]</td><td>1639.7</td><td>81.7</td><td>75.4</td><td>61.5</td><td>54.2</td><td>49.8</td><td>83.0</td><td>794</td><td>77.4</td><td>84.2</td><td>45.0</td></tr><tr><td>Qwen2-VL-7B [85]</td><td>1639.2</td><td>83.0</td><td>76.0</td><td>60.7</td><td>62.0</td><td>54.1</td><td>83.0</td><td>845</td><td>84.3</td><td>88.4</td><td>50.6</td></tr><tr><td>ChatRex-7B</td><td>1544.0</td><td>81.1</td><td>74.4</td><td>57.5</td><td>41.5</td><td>46.7</td><td>79.1</td><td>626</td><td>69.1</td><td>87.6</td><td>39.1</td></tr></table>

Table 3. Comparison of different models on multimodal benchmarks.

Common Object Detection. As shown in Tab. 2, ChatRex achieves a  \(48.2\mathrm{mAP}\)  on the COCO dataset, which is comparable to conventional object detectors like DINO [102], indicating that ChatRex possesses strong perception capabilities. In contrast, other MLLMs generally exhibit low recall rates. This discrepancy arises from the multi-object nature of COCO, where each image contains multiple categories with numerous instances. The low recall rate implies that current MLLMs face significant challenges in detecting multiple objects, which is a common requirement in real-world scenarios. Furthermore, we identified specific issues with general MLLMs such as InternVL2 and Qwen2-VL, which have a tendency to repeatedly generate the same coordinates until reaching the model's maximum output length. A detailed analysis of these problems is provided in the Appendix, highlighting areas for potential improvement in future work.

Long-tailed Object Detection. We further evaluate ChatRex on the more challenging LVIS [25] dataset, which encompasses 1,203 object categories. ChatRex achieved a  \(42.6\mathrm{mAP}\) , surpassing open-set detection models like Grounding DINO [52] and GLIP [39] and is on par with T-Rex2 [29]. We attribute this performance to the strong

semantic understanding capabilities of the LLM. Within the ChatRex model structure, the LLM primarily functions to classify bounding boxes generated by the proposal model. By aligning visual features with the textual space through comprehensive training and data optimization, the LLM is able to accurately classify a broad spectrum of categories, thereby demonstrating its robustness in handling complex, long-tailed object detection scenarios.

Referring Object Detection. Referring object detection involves identifying an object based on a given description. We evaluate ChatRex on the RefCOCO, RefCOCO+, and RefCOCOg benchmarks, which predominantly focus on single-object detection, where each expression generally corresponds to a single object. As shown in Tab. 2, ChatRex possesses strong referring capabilities, which are crucial for tackling complex perception tasks.

## 5.2. Understanding Capability Evaluation

General Multimodal Benchmarks. We evaluate ChatRex on various academic multimodal benchmarks including MME [23], MMBench [53], SEED[35], MMstar [11], MM-Vet [96], MMMU [98], AI2D [31], OCRBench [54], TextVQA [77], POPE [40], and HallusionBench [24]. As

<table><tr><td rowspan="2">Method</td><td colspan="2">LVIS</td><td colspan="2">PACO</td></tr><tr><td>SS</td><td>S-IoU</td><td>SS</td><td>S-IoU</td></tr><tr><td>LLaVA-1.5 [50]</td><td>49.0</td><td>19.8</td><td>42.2</td><td>14.6</td></tr><tr><td>Kosmos-2 [65]</td><td>39.0</td><td>8.7</td><td>32.1</td><td>4.8</td></tr><tr><td>Shikra-7B [10]</td><td>49.7</td><td>19.8</td><td>43.6</td><td>11.4</td></tr><tr><td>GPT4RoI-7B [106]</td><td>51.3</td><td>12.0</td><td>48.0</td><td>12.1</td></tr><tr><td>Ferret-7B [94]</td><td>63.8</td><td>36.6</td><td>58.7</td><td>26.0</td></tr><tr><td>Osprey-7B [97]</td><td>65.2</td><td>38.2</td><td>73.1</td><td>52.7</td></tr><tr><td>VisionLLM v2-7B [87]</td><td>68.9</td><td>46.3</td><td>67.7</td><td>44.0</td></tr><tr><td>SPHINX-V-7B [48]</td><td>87.1</td><td>62.9</td><td>80.0</td><td>55.0</td></tr><tr><td>ChatRex-7B (Ours)</td><td>89.8</td><td>82.6</td><td>91.4</td><td>85.1</td></tr></table>

Table 4. Comparison on referring object classification task.  

<table><tr><td rowspan="2">Training With Stage-2</td><td colspan="7">Understanding</td></tr><tr><td>MME</td><td>MMB</td><td>MMStar</td><td>SEEDT</td><td>MMMU</td><td>POPE</td><td>Hallusion</td></tr><tr><td>No</td><td>1388.8</td><td>76.8</td><td>44.5</td><td>72.9</td><td>46.0</td><td>80.3</td><td>34.0</td></tr><tr><td>Yes</td><td>1439.1</td><td>76.7</td><td>46.2</td><td>73.0</td><td>52.0</td><td>86.0</td><td>37.6</td></tr><tr><td colspan="8">Perception</td></tr><tr><td>Training With Stage-2</td><td>COOC mAP</td><td>LVIS mAP</td><td>Ref+ val</td><td>Ref+ testA</td><td>Ref+ testB</td><td>Refg test</td><td>Refg val</td></tr><tr><td>No</td><td>47.8</td><td>42.3</td><td>85.9</td><td>90.9</td><td>79.7</td><td>89.4</td><td>88.8</td></tr><tr><td>Yes</td><td>48.7</td><td>43.4</td><td>88.6</td><td>92.2</td><td>82.2</td><td>90.6</td><td>90.3</td></tr></table>

Table 5. Ablation of the impact of Stage-2 training on the perception and understanding capabilities of ChatRex. We remove the LLaVA-Onevision data in the final stage for quick validation.  

<table><tr><td>Eval Stage</td><td>COCOMAP</td><td>LVISmAP</td><td>Ref+val</td><td>Ref+testA</td><td>Ref+testB</td><td>Refgtest</td><td>Refgval</td></tr><tr><td>Stage-2</td><td>48.7</td><td>42.2</td><td>86.5</td><td>91.9</td><td>80.9</td><td>89.6</td><td>89.0</td></tr><tr><td>Stage-3</td><td>48.2</td><td>42.6</td><td>89.8</td><td>91.9</td><td>79.3</td><td>89.8</td><td>90.0</td></tr></table>

shown in Table 3, ChatRex demonstrates strong multimodal capabilities, though there remains a performance gap compared to state-of-the-art models like Qwen2-VL and InternVL2. We believe this performance gap can be narrowed with larger-scale data and improved visual representations, such as the AnyRes strategy [37]. Furthermore, ChatRex's enhanced perception capabilities enable it to provide object grounding information during conversations, extending its applicability to a broader range of real-world scenarios.

Region Caption Benchmarks. In addition to image-level understanding, ChatRex demonstrates strong region-level understanding capabilities. Following Osprey [97], we evaluate the referring object classification task on the LVIS [25] and PACO [68] datasets. In this task, given the object index, the model is prompted to output the category name of the specified region. The evaluation metrics include Semantic Similarity (SS) and Semantic Intersection over Union (S-IOU) [72]. As shown in Tab. 4, ChatRex achieves state-of-the-art results, highlighting its robust region classification capabilities.

Table 6. Ablation of the perception capabilities of ChatRex at different stage checkpoints.  

<table><tr><td rowspan="2">Method</td><td colspan="7">Understanding</td></tr><tr><td>MME</td><td>MMB</td><td>MMStar</td><td>SEED1</td><td>MMMU</td><td>POPE</td><td>Hallusion</td></tr><tr><td>Baseline</td><td>1439.1</td><td>76.7</td><td>46.2</td><td>73.0</td><td>52.0</td><td>86.0</td><td>37.6</td></tr><tr><td>w/o ConvNeXt</td><td>1341.9</td><td>70.4</td><td>42.7</td><td>65.4</td><td>43.3</td><td>83.8</td><td>24.4</td></tr><tr><td colspan="8">Perception</td></tr><tr><td rowspan="2">Method</td><td>COOC</td><td>LVIS</td><td>Ref+</td><td>Ref+</td><td>Ref+</td><td>Refg</td><td>Refg</td></tr><tr><td>mAP</td><td>mAP</td><td>val</td><td>testA</td><td>testB</td><td>test</td><td>val</td></tr><tr><td>Baseline</td><td>48.7</td><td>43.4</td><td>88.6</td><td>92.2</td><td>82.2</td><td>90.6</td><td>90.3</td></tr><tr><td>w/o ConNeXt</td><td>26.0</td><td>22.0</td><td>66.8</td><td>73.2</td><td>61.4</td><td>73.1</td><td>72.5</td></tr></table>

Table 7. Ablation of the dual vision encoder designing in ChatRex. We evaluate the impact of removing the ConvNeXt high-resolution encoder on perception and understanding tasks. We remove the LLaVA-Onevision data in Stage-3 for quick validation.

## 5.3. Ablation Experiments

Mutual Benefits of Perception and Understanding. We conduct ablation experiments to analyze the mutual influence of perception and understanding in ChatRex. As shown in Tab. 5, incorporating perception training in Stage-2 enhances the model's multimodal understanding, demonstrating that stronger perception contributes to improved understanding. Additionally, training with Stage-2 also leads to a performance boost in perception, highlighting the effectiveness of the Rexverse-2M dataset in strengthening perception capabilities.

To further examine this interaction, we compare the performance of the perception between Stage-2 and Stage-3, as shown in Tab. 6. The results indicate that the perception performance of ChatRex improves with Stage-3 training, suggesting that multimodal data not only enhances understanding but also refines perception. This reinforces the interdependence of perception and understanding, demonstrating that their integration leads to mutual enhancement and a more robust multimodal model.

Ablation on ChatRex Architecture. In ChatRex, we adopt a dual vision encoder design, where object features are extracted from the high-resolution encoder to serve as object tokens. To assess the effectiveness of this design, we conduct an ablation study by removing the high-resolution encoder and instead extracting object features from the low-resolution CLIP encoder. As shown in Tab. 7, the results indicate that the removal of the high-resolution encoder leads to a decline in both perception and understanding performance, with a more significant drop observed in perception. We attribute this to the fact that perception tasks heavily rely on higher input image resolutions to capture fine-grained details, which aligns with established findings in object detection community, where increasing image resolution generally improves detection accuracy and overall performance.

# 6. Conclusions

In this work, we reveal the perception drawback in existing MLLMs due to their conflict modeling between perception and understanding, and the lack of data that effectively balance these two aspects. To address these issues, we

introduce ChatRex, a model with a decoupled architecture, along with Rexverse-2M, a multi-granularity dataset designed to balance these two aspects. ChatRex demonstrates strong perception abilities while also excelling in multimodal understanding and dialog capabilities. The synergy between perception and understanding allows ChatRex to be highly interactive by grounding mentioned objects within visual contexts during dialogue. We believe that perception and understanding are both critical for MLLMs, as their integration can significantly enhance model capabilities and unlock a wide range of novel applications.

# References

[1] Marah Abdin, Jyoti Aneja, Hany Awadalla, Ahmed Awadallah, Ammar Ahmad Awan, Nguyen Bach, Amit Bahree, Arash Bakhtiari, Jianmin Bao, Harkirat Behl, et al. Phi-3 technical report: A highly capable language model locally on your phone. arXiv preprint arXiv:2404.14219, 2024. 1  
[2] Josh Achiam, Steven Adler, Sandhini Agarwal, Lama Ahmad, Ilge Akkaya, Florencia Leoni Aleman, Diogo Almeida, Janko Altenschmidt, Sam Altman, Shyamal Anadkat, et al. Gpt-4 technical report. arXiv preprint arXiv:2303.08774, 2023. 1  
[3] Pravesh Agrawal, Szymon Antoniak, Emma Bou Hanna, Devendra Chaplot, Jessica Chudnovsky, Saurabh Garg, Theophile Gervet, Soham Ghosh, Amélie Héliou, Paul Jacob, et al. Pixtral 12b. arXiv preprint arXiv:2410.07073, 2024. 1, 3  
[4] Jean-Baptiste Alayrac, Jeff Donahue, Pauline Luc, Antoine Miech, Iain Barr, Yana Hasson, Karel Lenc, Arthur Mensch, Katherine Millican, Malcolm Reynolds, et al. Flamingo: a visual language model for few-shot learning. NeurIPS, 35:23716-23736, 2022. 1, 3  
[5] Jinze Bai, Shuai Bai, Yunfei Chu, Zeyu Cui, Kai Dang, Xiaodong Deng, Yang Fan, Wenbin Ge, Yu Han, Fei Huang, Binyuan Hui, Luo Ji, Mei Li, Junyang Lin, Runji Lin, Dayiheng Liu, Gao Liu, Chengqiang Lu, Keming Lu, Jianxin Ma, Rui Men, Xingzhang Ren, Xuancheng Ren, Chuanqi Tan, Sinan Tan, Jianhong Tu, Peng Wang, Shijie Wang, Wei Wang, Shengguang Wu, Benfeng Xu, Jin Xu, An Yang, Hao Yang, Jian Yang, Shusheng Yang, Yang Yao, Bowen Yu, Hongyi Yuan, Zheng Yuan, Jianwei Zhang, Xingxuan Zhang, Yichang Zhang, Zhenru Zhang, Chang Zhou, Jingren Zhou, Xiaohuan Zhou, and Tianhang Zhu. Qwen technical report. arXiv preprint arXiv:2309.16609, 2023. 1  
[6] Jinze Bai, Shuai Bai, Shusheng Yang, Shijie Wang, Sinan Tan, Peng Wang, Junyang Lin, Chang Zhou, and Jingren Zhou. Qwen-vl: A frontier large vision-language model with versatile abilities. arXiv preprint arXiv:2308.12966, 2023. 1, 3  
[7] Minwoo Byeon, Beomhee Park, Haecheon Kim, Sungjun Lee, Woonhyuk Baek, and Saehoon Kim. Coyo-700m: Image-text pair dataset. https://github.com/kakaobrain/coyo-dataset, 2022.5

[8] Nicolas Carion, Francisco Massa, Gabriel Synnaeve, Nicolas Usunier, Alexander Kirillov, and Sergey Zagoruyko. End-to-end object detection with transformers. In European conference on computer vision, pages 213-229. Springer, 2020. 3, 7  
[9] Guiming Hardy Chen, Shunian Chen, Ruifei Zhang, Junying Chen, Xiangbo Wu, Zhiyi Zhang, Zhihong Chen, Jianquan Li, Xiang Wan, and Benyou Wang. Allava: Harnessing gpt4v-synthesized data for a lite vision-language model. arXiv preprint arXiv:2402.11684, 2024. 6  
[10] Keqin Chen, Zhao Zhang, Weili Zeng, Richong Zhang, Feng Zhu, and Rui Zhao. Shikra: Unleashing multimodal llm's referential dialogue magic. arXiv preprint arXiv:2306.15195, 2023. 1, 3, 7, 8, 2  
[11] Lin Chen, Jinsong Li, Xiaoyi Dong, Pan Zhang, Yuhang Zang, Zehui Chen, Haodong Duan, Jiaqi Wang, Yu Qiao, Dahua Lin, et al. Are we on the right way for evaluating large vision-language models? arXiv preprint arXiv:2403.20330, 2024. 7  
[12] Ting Chen, Saurabh Saxena, Lala Li, David J Fleet, and Geoffrey Hinton. Pix2seq: A language modeling framework for object detection. arXiv preprint arXiv:2109.10852, 2021. 1, 3, 7  
[13] Xi Chen, Xiao Wang, Soravit Changpinyo, AJ Piergiovanni, Piotr Padlewski, Daniel Salz, Sebastian Goodman, Adam Grycner, Basil Mustafa, Lucas Beyer, et al. Pali: A jointly-scaled multilingual language-image model. In ICLR, 2022. 1, 3  
[14] Zhe Chen, Weiyun Wang, Hao Tian, Shenglong Ye, Zhang-wei Gao, Erfei Cui, Wenwen Tong, Kongzhi Hu, Jiapeng Luo, Zheng Ma, et al. How far are we to gpt-4v? closing the gap to commercial multimodal models with opensource suites. arXiv:2404.16821, 2024. 1, 2, 3, 5, 6, 7  
[15] Wei-Lin Chiang, Zhuohan Li, Zi Lin, Ying Sheng, Zhang-hao Wu, Hao Zhang, Lianmin Zheng, Siyuan Zhuang, Yonghao Zhuang, Joseph E. Gonzalez, Ion Stoica, and Eric P. Xing. Vicuna: An open-source chatbot impressing gpt-4 with  \(90\%\)  * chatgpt quality, 2023. 1  
[16] Wenliang Dai, Junnan Li, Dongxu Li, Anthony Meng Huat Tiong, Junqi Zhao, Weisheng Wang, Boyang Li, Pascale Fung, and Steven C. H. Hoi. Instructclip: Towards general-purpose vision-language models with instruction tuning. In NeurIPS, 2023. 1, 3, 7  
[17] Wenliang Dai, Nayeon Lee, Boxin Wang, Zhuoling Yang, Zihan Liu, Jon Barker, Tuomas Rintamaki, Mohammad Shoeybi, Bryan Catanzaro, and Wei Ping. NvIm: Open frontier-class multimodal llms. arXiv preprint arXiv:2409.11402, 2024.3  
[18] Matt Deitke, Christopher Clark, Sangho Lee, Rohun Tripathi, Yue Yang, Jae Sung Park, Mohammadreza Salehi, Niklas Muennighoff, Kyle Lo, Luca Soldaini, et al. Molmo and pixmo: Open weights and open data for state-of-the-art multimodal models. arXiv preprint arXiv:2409.17146, 2024. 1, 3  
[19] Jia Deng, Wei Dong, Richard Socher, Li-Jia Li, Kai Li, and Li Fei-Fei. Imagenet: A large-scale hierarchical image database. In CVPR, pages 248–255, 2009. 1

[20] Xiaoyi Dong, Pan Zhang, Yuhang Zang, Yuhang Cao, Bin Wang, Linke Ouyang, Songyang Zhang, Haodong Duan, Wenwei Zhang, Yining Li, Hang Yan, Yang Gao, Zhe Chen, Xinyue Zhang, Wei Li, Jingwen Li, Wenhai Wang, Kai Chen, Conghui He, Xingcheng Zhang, Jifeng Dai, Yu Qiao, Dahua Lin, and Jiaqi Wang. Internlm-xcomposer2-4khd: A pioneering large vision-language model handling resolutions from 336 pixels to 4k HD. arXiv: 2404.06512, 2024. 3  
[21] Alexey Dosovitskiy, Lucas Beyer, Alexander Kolesnikov, Dirk Weissenborn, Xiaohua Zhai, Thomas Unterthiner, Mostafa Dehghani, Matthias Minderer, Georg Heigold, Sylvain Gelly, Jakob Uszkoreit, and Neil Houlsby. An image is worth 16x16 words: Transformers for image recognition at scale. In ICLR, 2021. 4  
[22] Abhimanyu Dubey, Abhinav Jauhri, Abhinav Pandey, Abhishek Kadian, Ahmad Al-Dahle, Aiesha Letman, Akhil Mathur, Alan Schelten, Amy Yang, Angela Fan, et al. The llama 3 herd of models. arXiv preprint arXiv:2407.21783, 2024. 1, 2, 6  
[23] Chaoyou Fu, Peixian Chen, Yunhang Shen, Yulei Qin, Mengdan Zhang, Xu Lin, Jinrui Yang, Xiawu Zheng, Ke Li, Xing Sun, Yunsheng Wu, and Rongrong Ji. Mme: A comprehensive evaluation benchmark for multimodal large language models, 2024. 7  
[24] Tianrui Guan, Fuxiao Liu, Xiyang Wu, Ruiqi Xian, Zongxia Li, Xiaoyu Liu, Xijun Wang, Lichang Chen, Furong Huang, Yaser Yacoob, et al. Hallusionbench: An advanced diagnostic suite for entangled language hallucination & visual illusion in large vision-language models. arXiv preprint arXiv:2310.14566, 2023. 7  
[25] Agrim Gupta, Piotr Dollar, and Ross Girshick. Lvis: A dataset for large vocabulary instance segmentation. In Proceedings of the IEEE/CVF conference on computer vision and pattern recognition, pages 5356-5364, 2019. 3, 6, 7, 8  
[26] Kaiming He, Georgia Gkioxari, Piotr Dólar, and Ross Girshick. Mask r-cnn. In ICCV, pages 2961-2969, 2017. 4  
[27] Zheng Huang, Kai Chen, Jianhua He, Xiang Bai, Dimosthenis Karatzas, Shijian Lu, and CV Jawahar. Icdar2019 competition on scanned receiptOCR and information extraction. In 2019 International Conference on Document Analysis and Recognition (ICDAR), pages 1516-1520. IEEE, 2019. 6  
[28] Dongfu Jiang, Xuan He, Huaye Zeng, Con Wei, Max Ku, Qian Liu, and Wenhu Chen. Mantis: Interleaved multi-image instruction tuning. arXiv:2405.01483, 2024. 3  
[29] Qing Jiang, Feng Li, Zhaoyang Zeng, Tianhe Ren, Shilong Liu, and Lei Zhang. T-rex2: Towards generic object detection via text-visual prompt synergy. In European Conference on Computer Vision, pages 38-57. Springer, 2025. 3, 7, 1  
[30] Sahar Kazemzadeh, Vicente Ordonez, Mark Matten, and Tamara Berg. Referitgame: Referring to objects in photographs of natural scenes. In Proceedings of the 2014 conference on empirical methods in natural language processing (EMNLP), pages 787-798, 2014. 3, 6  
[31] Aniruddha Kembhavi, Mike Salvato, Eric Kolve, Minjoon Seo, Hannaneh Hajishirzi, and Ali Farhadi. A diagram is

worth a dozen images. In Computer Vision-ECCV 2016: 14th European Conference, Amsterdam, The Netherlands, October 11-14, 2016, Proceedings, Part IV 14, pages 235-251. Springer, 2016. 7  
[32] Alexander Kirillov, Eric Mintun, Nikhila Ravi, Hanzi Mao, Chloé Rolland, Laura Gustafson, Tete Xiao, Spencer Whitehead, Alexander C. Berg, Wan-Yen Lo, Piotr Dólar, and Ross B. Girshick. Segment anything. arXiv: 2304.02643, 2023. 3, 6  
[33] Alina Kuznetsova, Hassan Rom, Neil Alldrin, Jasper Uijlings, Ivan Krasin, Jordi Pont-Tuset, Shahab Kamali, Stefan Popov, Matteo Malloci, Alexander Kolesnikov, et al. The open images dataset v4: Unified image classification, object detection, and visual relationship detection at scale. International journal of computer vision, 128(7): 1956-1981, 2020. 6  
[34] Xin Lai, Zhuotao Tian, Yukang Chen, Yanwei Li, Yuhui Yuan, Shu Liu, and Jiaya Jia. Lisa: Reasoning segmentation via large language model. arXiv preprint arXiv:2308.00692, 2023. 3  
[35] Bohao Li, Rui Wang, Guangzhi Wang, Yuying Ge, Yixiao Ge, and Ying Shan. Seed-bench: Benchmarking multimodal llms with generative comprehension. arXiv preprint arXiv:2307.16125, 2023. 7  
[36] Dongxu Li, Yudong Liu, Haoning Wu, Yue Wang, Zhiqi Shen, Bowen Qu, Xinyao Niu, Guoyin Wang, Bei Chen, and Junnan Li. Aria: An open multimodal native mixture-of-experts model. arXiv preprint arXiv:2410.05993, 2024. 1, 3  
[37] Feng Li, Renrui Zhang, Hao Zhang, Yuanhan Zhang, Bo Li, Wei Li, Zejun Ma, and Chunyuan Li. Llava-last-interleave: Tackling multi-image, video, and 3d in large multimodal models. arXiv preprint arXiv:2407.07895, 2024. 3, 6, 7, 8  
[38] Junnan Li, Dongxu Li, Silvio Savarese, and Steven Hoi. Blip-2: Bootstrapping language-image pre-training with frozen image encoders and large language models. In ICML, pages 19730–19742. PMLR, 2023. 7  
[39] Liunian Harold Li, Pengchuan Zhang, Haotian Zhang, Jianwei Yang, Chunyuan Li, Yiwu Zhong, Lijuan Wang, Lu Yuan, Lei Zhang, Jenq-Neng Hwang, et al. Grounded language-image pre-training. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition, pages 10965-10975, 2022. 7  
[40] Yifan Li, Yifan Du, Kun Zhou, Jinpeng Wang, Wayne Xin Zhao, and Ji-Rong Wen. Evaluating object hallucination in large vision-language models. In EMNLP, pages 292–305, 2023. 7  
[41] Yanwei Li, Yuechen Zhang, Chengyao Wang, Zhisheng Zhong, Yixin Chen, Ruihang Chu, Shaoteng Liu, and Jiaya Jia. Mini-gemini: Mining the potential of multi-modality vision language models. arXiv: 2403.18814, 2024. 3  
[42] Yanwei Li, Yuechen Zhang, Chengyao Wang, Zhisheng Zhong, Yixin Chen, Ruihang Chu, Shaoteng Liu, and Jiaya Jia. Mini-gemini: Mining the potential of multi-modality vision language models. arXiv preprint arXiv:2403.18814, 2024. 7  
[43] Zhang Li, Biao Yang, Qiang Liu, Zhiyin Ma, Shuo Zhang, Jingxu Yang, Yabo Sun, Yuliang Liu, and Xiang Bai.

Monkey: Image resolution and text label are important things for large multi-modal models. arXiv preprint arXiv:2311.06607, 2023. 3  
[44] Bin Lin, Yang Ye, Bin Zhu, Jiaxi Cui, Munan Ning, Peng Jin, and Li Yuan. Video-llava: Learning united visual representation by alignment before projection. arXiv preprint arXiv:2311.10122, 2023. 3  
[45] Ji Lin, Hongxu Yin, Wei Ping, Pavlo Molchanov, Mohammad Shoeybi, and Song Han. Vila: On pre-training for visual language models. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition, pages 26689-26699, 2024. 3  
[46] Tsung-Yi Lin, Michael Maire, Serge J. Belongie, James Hays, Pietro Perona, Deva Ramanan, Piotr Dólár, and C. Lawrence Zitnick. Microsoft COCO: common objects in context. In ECCV, pages 740-755, 2014. 1, 3, 6  
[47] Weifeng Lin, Xinyu Wei, Ruichuan An, Peng Gao, Bocheng Zou, Yulin Luo, Siyuan Huang, Shanghang Zhang, and Hongsheng Li. Draw-and-understand: Leveraging visual prompts to enable mllms to comprehend what you want. arXiv preprint arXiv:2403.20271, 2024. 6  
[48] Ziyi Lin, Chris Liu, Renrui Zhang, Peng Gao, Longtian Qiu, Han Xiao, Han Qiu, Chen Lin, Wenqi Shao, Keqin Chen, et al. *Sphinx*: The joint mixing of weights, tasks, and visual embeddings for multi-modal large language models. arXiv preprint arXiv:2311.07575, 2023. 3, 8  
[49] Haotian Liu, Chunyuan Li, Yuheng Li, and Yong Jae Lee. Improved baselines with visual instruction tuning. arXiv: 2310.03744, 2023. 6  
[50] Haotian Liu, Chunyuan Li, Qingyang Wu, and Yong Jae Lee. Visual instruction tuning. In NeurIPS, 2023. 3, 5, 8  
[51] Haotian Liu, Chunyuan Li, Yuheng Li, Bo Li, Yuanhan Zhang, Sheng Shen, and Yong Jae Lee. Llava-last: Improved reasoning,OCR,and world knowledge,2024.3,7  
[52] Shilong Liu, Zhaoyang Zeng, Tianhe Ren, Feng Li, Hao Zhang, Jie Yang, Qing Jiang, Chunyuan Li, Jianwei Yang, Hang Su, et al. Grounding dino: Marrying dino with grounded pre-training for open-set object detection. arXiv preprint arXiv:2303.05499, 2023. 7  
[53] Yuan Liu, Haodong Duan, Yuanhan Zhang, Bo Li, Songyang Zhang, Wangbo Zhao, Yike Yuan, Jiaqi Wang, Conghui He, Ziwei Liu, Kai Chen, and Dahua Lin. Mmbench: Is your multi-modal model an all-around player? arXiv: 2307.06281, 2023. 7  
[54] Yuliang Liu, Zhang Li, Mingxin Huang, Biao Yang, Wenwen Yu, Chunyuan Li, Xu-Cheng Yin, Cheng-Lin Liu, Lianwen Jin, and Xiang Bai. Ocrbench: on the hidden mystery ofOCR in large multimodal models. Science China Information Sciences, 67(12):220102, 2024. 7  
[55] Ze Liu, Yutong Lin, Yue Cao, Han Hu, Yixuan Wei, Zheng Zhang, Stephen Lin, and Baining Guo. Swin transformer: Hierarchical vision transformer using shifted windows. In ICCV, pages 10012-10022, 2021. 1  
[56] Zhuang Liu, Hanzi Mao, Chao-Yuan Wu, Christoph Feichtenhofer, Trevor Darrell, and Saining Xie. A convnet for the 2020s. In Proceedings of the IEEE/CVF conference on computer vision and pattern recognition, pages 11976-11986, 2022. 2, 4

[57] Shangbang Long, Siyang Qin, Dmitry Panteleev, Alessandro Bissacco, Yasuhisa Fujii, and Michalis Raptis. Towards end-to-end unified scene text detection and layout analysis. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition, pages 1049-1059, 2022. 6  
[58] Gen Luo, Yiyi Zhou, Yuxin Zhang, Xiawu Zheng, Xiaoshuai Sun, and Rongrong Ji. Feast your eyes: Mixture-of-resolution adaptation for multimodal large language models. arXiv preprint arXiv:2403.03003, 2024. 7  
[59] Gen Luo, Yiyi Zhou, Yuxin Zhang, Xiawu Zheng, Xiaoshuai Sun, and Rongrong Ji. Feast your eyes: Mixture-of-resolution adaptation for multimodal large language models. arXiv preprint arXiv:2403.03003, 2024. 3  
[60] Tengchao Lv, Yupan Huang, Jingye Chen, Lei Cui, Shuming Ma, Yaoyao Chang, Shaohan Huang, Wenhui Wang, Li Dong, Weiyao Luo, et al. Kosmos-2.5: A multimodal literate model. arXiv preprint arXiv:2309.11419, 2023. 1, 3  
[61] Chuofan Ma, Yi Jiang, Jiannan Wu, Zehuan Yuan, and Xiaojuan Qi. Groma: Localized visual tokenization for grounding multimodal large language models. arXiv preprint arXiv:2404.13013, 2024. 1, 2, 3, 7  
[62] Junhua Mao, Jonathan Huang, Alexander Toshev, Oana Camburu, Alan L Yuille, and Kevin Murphy. Generation and comprehension of unambiguous object descriptions. In CVPR, pages 11-20, 2016. 3, 6  
[63] Brandon McKinzie, Zhe Gan, Jean-Philippe Fauconnier, Sam Dodge, Bowen Zhang, Philipp Dufter, Dhruti Shah, Xianzhi Du, Futang Peng, Floris Weers, Anton Belyi, Haotian Zhang, Karanjeet Singh, Doug Kang, Ankur Jain, Hongyu He, Max Schwarzer, Tom Gunter, Xiang Kong, Aonan Zhang, Jianyu Wang, Chong Wang, Nan Du, Tao Lei, Sam Wiseman, Guoli Yin, Mark Lee, Zirui Wang, Ruoming Pang, Peter Grasch, Alexander Toshev, and Yinfei Yang. MM1: methods, analysis & insights from multimodal LLM pre-training. arXiv: 2403.09611, 2024. 3  
[64] OpenAI. Gpt-4v(ison) system card. https://cdn.openai.com/papers/GPTV_System/Card.pdf, 2023.1,3  
[65] Zhiliang Peng, Wenhui Wang, Li Dong, Yaru Hao, Shaohan Huang, Shuming Ma, and Furu Wei. Kosmos-2: Grounding multimodal large language models to the world. arXiv preprint arXiv:2306.14824, 2023. 3, 8  
[66] Renjie Pi, Lewei Yao, Jiahui Gao, Jipeng Zhang, and Tong Zhang. Perceptiongpt: Effectively fusing visual perception into llm. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition, pages 27124-27133, 2024. 3  
[67] Alec Radford, Jong Wook Kim, Chris Hallacy, Aditya Ramesh, Gabriel Goh, Sandhini Agarwal, Girish Sastry, Amanda Askell, Pamela Mishkin, Jack Clark, Gretchen Krueger, and Ilya Sutskever. Learning transferable visual models from natural language supervision. In ICML, pages 8748-8763, 2021. 4  
[68] Vignesh Ramanathan, Anmol Kalia, Vladan Petrovic, Yi Wen, Baixue Zheng, Baishan Guo, Rui Wang, Aaron Marquez, Rama Kovvuri, Abhishek Kadian, et al. Paco: Parts

and attributes of common objects. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition, pages 7141-7151, 2023. 6, 8  
[69] Hanoona Rasheed, Muhammad Maaz, Sahal Shaji, Abdelrahman Shaker, Salman Khan, Hisham Cholakkal, Rao M Anwer, Eric Xing, Ming-Hsuan Yang, and Fahad S Khan. Glamm: Pixel grounding large multimodal model. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition, pages 13009-13018, 2024. 3  
[70] Shaoqing Ren, Kaiming He, Ross B. Girshick, and Jian Sun. Faster R-CNN: towards real-time object detection with region proposal networks. In NIPS, pages 91-99, 2015. 7  
[71] Tianhe Ren, Qing Jiang, Shilong Liu, Zhaoyang Zeng, Wenlong Liu, Han Gao, Hongjie Huang, Zhengyu Ma, Xiaoke Jiang, Yihao Chen, et al. Grounding dino 1.5: Advance the" edge" of open-set object detection. arXiv preprint arXiv:2405.10300, 2024. 2, 6  
[72] Hamid Rezatofighi, Nathan Tsoi, JunYoung Gwak, Amir Sadeghian, Ian Reid, and Silvio Savarese. Generalized intersection over union: A metric and a loss for bounding box regression. In Proceedings of the IEEE/CVF conference on computer vision and pattern recognition, pages 658-666, 2019. 8, 1  
[73] Christoph Schuhmann, Romain Beaumont, Richard Venu, Cade Gordon, Ross Wightman, Mehdi Cherti, Theo Coombes, Aarush Katta, Clayton Mullis, Mitchell Wortman, et al. Laion-5b: An open large-scale dataset for training next generation image-text models. NeurIPS, 35: 25278-25294, 2022. 4  
[74] Shuai Shao, Zijian Zhao, Boxun Li, Tete Xiao, Gang Yu, Xiangyu Zhang, and Jian Sun. Crowdhuman: A benchmark for detecting human in a crowd. arXiv preprint arXiv:1805.00123, 2018. 6  
[75] Shuai Shao, Zeming Li, Tianyuan Zhang, Chao Peng, Gang Yu, Xiangyu Zhang, Jing Li, and Jian Sun. Objects365: A large-scale, high-quality dataset for object detection. In ICCV, pages 8430-8439, 2019. 3, 6  
[76] Min Shi, Fuxiao Liu, Shihao Wang, Shijia Liao, Subhashree Radhakrishnan, De-An Huang, Hongxu Yin, Karan Sapra, Yaser Yacoob, Humphrey Shi, et al. Eagle: Exploring the design space for multimodal llms with mixture of encoders. arXiv preprint arXiv:2408.15998, 2024. 3, 7  
[77] Amanpreet Singh, Vivek Natarajan, Meet Shah, Yu Jiang, Xinlei Chen, Dhruv Batra, Devi Parikh, and Marcus Rohrbach. Towards vqa models that can read. In Proceedings of the IEEE/CVF conference on computer vision and pattern recognition, pages 8317-8326, 2019. 7  
[78] Rohan Taori, Ishaan Gulrajani, Tianyi Zhang, Yann Dubois, Xuechen Li, Carlos Guestrin, Percy Liang, and Tatsunori B. Hashimoto. Stanford alpaca: An instruction-following llama model. https://github.com/tatsu-lab/stanford_alpaca, 2023.1  
[79] Gemini Team, Rohan Anil, Sebastian Borgeaud, Yonghui Wu, Jean-Baptiste Alayrac, Jiahui Yu, Radu Soricut, Johan Schalkwyk, Andrew M Dai, Anja Hauth, et al. Gemini: a family of highly capable multimodal models. arXiv: 2312.11805, 2023. 1, 3

[80] InternLM Team. Internlm: A multilingual language model with progressively enhanced capabilities. https://github.com/InternLM/InternLM, 2023.1  
[81] Peter Tong, Ellis Brown, Penghao Wu, Sanghyun Woo, Adithya Jairam Vedagiri IYER, Sai Charitha Akula, Shusheng Yang, Jihan Yang, Manoj Middepogu, Ziteng Wang, et al. Cambrian-1: A fully open, vision-centric exploration of multimodal llms. Advances in Neural Information Processing Systems, 37:87310-87356, 2025. 7  
[82] Shengbang Tong, Ellis Brown, Penghao Wu, Sanghyun Woo, Manoj Middepogu, Sai Charitha Akula, Jihan Yang, Shusheng Yang, Adithya Iyer, Xichen Pan, et al. Cambrian1: A fully open, vision-centric exploration of multimodal llms. arXiv preprint arXiv:2406.16860, 2024. 3  
[83] Hugo Touvron, Thibaut Lavril, Gautier Izacard, Xavier Martinet, Marie-Anne Lachaux, Timothée Lacroix, Baptiste Roziere, Naman Goyal, Eric Hambro, Faisal Azhar, Aurélien Rodriguez, Armand Joulin, Edouard Grave, and Guillaume Lample. Llama: Open and efficient foundation language models. arXiv: 2302.13971, 2023. 1  
[84] Hugo Touvron, Louis Martin, Kevin Stone, Peter Albert, Amjad Almahairi, Yasmine Babaei, Nikolay Bashlykov, Soumya Batra, Prajjwal Bhargava, Shruti Bhosale, et al. Llama 2: Open foundation and fine-tuned chat models. arXiv: 2307.09288, 2023. 1  
[85] Peng Wang, Shuai Bai, Sinan Tan, Shijie Wang, Zhihao Fan, Jinze Bai, Keqin Chen, Xuejing Liu, Jialin Wang, Wenbin Ge, et al. Qwen2-v1: Enhancing vision-language model's perception of the world at any resolution. arXiv preprint arXiv:2409.12191, 2024. 1, 3, 7, 2  
[86] Weihan Wang, Qingsong Lv, Wenmeng Yu, Wenyi Hong, Ji Qi, Yan Wang, Junhui Ji, Zhuoyi Yang, Lei Zhao, Xixuan Song, et al. Cogvlm: Visual expert for pretrained language models. arXiv preprint arXiv:2311.03079, 2023. 3  
[87] Jiannan Wu, Muyan Zhong, Sen Xing, Zeqiang Lai, Zhaoyang Liu, Wenhai Wang, Zhe Chen, Xizhou Zhu, Lewei Lu, Tong Lu, et al. Visionllm v2: An end-to-end generalist multimodal large language model for hundreds of vision-language tasks. arXiv preprint arXiv:2406.08394, 2024. 3, 8  
[88] Bin Xiao, Haiping Wu, Weijian Xu, Xiyang Dai, Houdong Hu, Yumao Lu, Michael Zeng, Ce Liu, and Lu Yuan. Florence-2: Advancing a unified representation for a variety of vision tasks. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition, pages 4818–4829, 2024. 7  
[89] Ruyi Xu, Yuan Yao, Zonghao Guo, Junbo Cui, Zanlin Ni, Chunjiang Ge, Tat-Seng Chua, Zhiyuan Liu, Maosong Sun, and Gao Huang. Llava-uhd: an LMM perceiving any aspect ratio and high-resolution images. arXiv: 2403.11703, 2024. 3  
[90] Fuzhao Xue, Yukang Chen, Dacheng Li, Qinghao Hu, Ligeng Zhu, Xiuyu Li, Yunhao Fang, Haotian Tang, Shang Yang, Zhijian Liu, et al. Longvila: Scaling long-context visual language models for long videos. arXiv preprint arXiv:2408.10188, 2024.3  
[91] Le Xue, Manli Shu, Anas Awadalla, Jun Wang, An Yan, Senthil Purushwalkam, Honglu Zhou, Viraj Prabhu, Yu

tong Dai, Michael S Ryoo, et al. xgen-mm (blip-3): A family of open large multimodal models. arXiv preprint arXiv:2408.08872, 2024. 3  
[92] An Yang, Baosong Yang, Beichen Zhang, Binyuan Hui, Bo Zheng, Bowen Yu, Chengyuan Li, Dayiheng Liu, Fei Huang, Haoran Wei, et al. Qwen2.5 technical report. arXiv preprint arXiv:2412.15115, 2024. 4  
[93] Jianwei Yang, Hao Zhang, Feng Li, Xueyan Zou, Chunyuan Li, and Jianfeng Gao. Set-of-mark prompting unleashes extraordinary visual grounding in gpt-4v. arXiv preprint arXiv:2310.11441, 2023. 3  
[94] Haoxuan You, Haotian Zhang, Zhe Gan, Xianzhi Du, Bowen Zhang, Zirui Wang, Liangliang Cao, Shih-Fu Chang, and Yinfei Yang. Ferret: Refer and ground anything anywhere at any granularity. arXiv preprint arXiv:2310.07704, 2023. 1, 3, 7, 8, 2  
[95] Licheng Yu, Patrick Poirson, Shan Yang, Alexander C Berg, and Tamara L Berg. Modeling context in referring expressions. In ECCV, pages 69-85, 2016. 3, 6  
[96] Weihao Yu, Zhengyuan Yang, Linjie Li, Jianfeng Wang, Kevin Lin, Zicheng Liu, Xinchao Wang, and Lijuan Wang. Mm-vet: Evaluating large multimodal models for integrated capabilities. arXiv preprint arXiv:2308.02490, 2023. 7  
[97] Yuqian Yuan, Wentong Li, Jian Liu, Dongqi Tang, Xinjie Luo, Chi Qin, Lei Zhang, and Jianke Zhu. Osprey: Pixel understanding with visual instruction tuning. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition, pages 28202-28211, 2024. 6, 8  
[98] Xiang Yue, Yuansheng Ni, Kai Zhang, Tianyu Zheng, Ruoqi Liu, Ge Zhang, Samuel Stevens, Dongfu Jiang, Weiming Ren, Yuxuan Sun, et al. Mmmu: A massive multidiscipline multimodal understanding and reasoning benchmark for expert agi. arXiv preprint arXiv:2311.16502, 2023.7  
[99] Rowan Zellers, Yonatan Bisk, Ali Farhadi, and Yejin Choi. From recognition to cognition: Visual commonsense reasoning. In The IEEE Conference on Computer Vision and Pattern Recognition (CVPR), 2019. 6  
[100] Yufei Zhan, Yousong Zhu, Hongyin Zhao, Fan Yang, Ming Tang, and Jinqiao Wang. Griffon v2: Advancing multimodal perception with high-resolution scaling and visual-language co-referring. arXiv preprint arXiv:2403.09333, 2024.3  
[101] Yufei Zhan, Yousong Zhu, Zhiyang Chen, Fan Yang, Ming Tang, and Jinqiao Wang. Griffon: Spelling out all object locations at any granularity with large language models. In European Conference on Computer Vision, pages 405-422. Springer, 2025. 3  
[102] Hao Zhang, Feng Li, Shilong Liu, Lei Zhang, Hang Su, Jun Zhu, Lionel M Ni, and Heung-Yeung Shum. Dino: Detr with improved denoising anchor boxes for end-to-end object detection. arXiv preprint arXiv:2203.03605, 2022. 7, 1  
[103] Haotian Zhang, Mingfei Gao, Zhe Gan, Philipp Dufter, Nina Wenzel, Forrest Huang, Dhruti Shah, Xianzhi Du, Bowen Zhang, Yanghao Li, et al. Mm1. 5: Methods, anal

ysis & insights from multimodal llm fine-tuning. arXiv preprint arXiv:2409.20566, 2024. 7  
[104] Haotian Zhang, Haoxuan You, Philipp Dufter, Bowen Zhang, Chen Chen, Hong-You Chen, Tsu-Jui Fu, William Yang Wang, Shih-Fu Chang, Zhe Gan, et al. Ferretv2: An improved baseline for referring and grounding with large language models. arXiv preprint arXiv:2404.07973, 2024. 3  
[105] Hao Zhang, Hongyang Li, Feng Li, Tianhe Ren, Xueyan Zou, Shilong Liu, Shijia Huang, Jianfeng Gao, Chunyuan Li, Jainwei Yang, et al. Llava-grounding: Grounded visual chat with large multimodal models. In European Conference on Computer Vision, pages 19-35. Springer, 2025. 3  
[106] Shilong Zhang, Peize Sun, Shoufa Chen, Min Xiao, Wenqi Shao, Wenwei Zhang, Kai Chen, and Ping Luo. Gpt4roi: Instruction tuning large language model on region-of-interest. arXiv: 2307.03601, 2023. 8  
[107] Yuanhan Zhang, Qinghong Sun, Yichun Zhou, Zexin He, Zhenfei Yin, Kun Wang, Lu Sheng, Yu Qiao, Jing Shao, and Ziwei Liu. Bamboo: Building mega-scale vision dataset continually with human-machine synergy. arXiv preprint arXiv:2203.07845, 2022. 6  
[108] Xiangyu Zhao, Xiangtai Li, Haodong Duan, Haian Huang, Yining Li, Kai Chen, and Hua Yang. Mg-llava: Towards multi-granularity visual instruction tuning. arXiv preprint arXiv:2406.17770, 2024. 3  
[109] Chenchen Zhu, Fanyi Xiao, Andres Alvarado, Yasmine Babaei, Jiabo Hu, Hichem El-Mohri, Sean Culatana, Roshan Sumbaly, and Zhicheng Yan. Egoobjects: A large-scale egocentric dataset for fine-grained object understanding. In Proceedings of the IEEE/CVF International Conference on Computer Vision, pages 20110-20120, 2023. 6

# ChatRex: Taming Multimodal LLM for Joint Perception and Understanding Supplementary Material

## A. MLLM Evaluation Details on Detection Datasets

In this section, we explain our methodology for evaluating MLLMs on the object detection task, including the design of model-specific prompts, the visualization of output results, and a comprehensive analysis of the challenges and limitations encountered throughout the evaluation process.

### A.1. Prompt for Each MLLM

For each MLLM evaluated, we utilized either the prompts used in the original paper or manually crafted optimized prompts to maximize performance. The specific prompts used in our evaluation are detailed in Tab. 8,

### A.2. More Analysis on the Detection Results

The visualization results on the COCO dataset are presented in Fig. 5. The qualitative analysis indicates that most evaluated MLLMs suffer from a low recall rate, underscoring significant limitations in their object perception capabilities. Additionally, specific deficiencies are observed in certain models. For example, Shikra [10] exhibits a notable issue with coordinate offset, where the predicted bounding boxes fail to accurately enclose the target objects. This misalignment is primarily attributed to quantization errors inherent in the model. Moreover, during the evaluation phase, most models, excluding general-purpose MLLMs such as InternVL2 [14] and Qwen2-VL [85], frequently struggle to follow task-specific instructions. This observation highlights persistent challenges in the instruction-following capability within these models.

We also identified a distinct issue with general MLLMs during the evaluation process: a pattern of repeated output coordinates in their predictions. This repetition is not random but follows a systematic pattern. For example, in the case of Qwen2-VL-7B, the model consistently generates bounding box coordinates where each subsequent bounding box is derived by incrementally adjusting the preceding one. For example, the xmin and xmax values of the bounding boxes are increased by a fixed value, such as 24, as illustrated in the below block. We argue this behavior stems from the auto-regressive coordinate prediction mechanism. The reliance on previously predicted coordinates introduces a probabilistic bias, causing subsequent predictions to deviate systematically as regular modifications of earlier outputs. This limitation underscores the model's inability to independently and accurately generate coordinates without cumulative error propagation.

### Example of repeated coordinate prediction in Qwen2-VL-7B.

Response: [ {class: car, rect: [234, 186, 370, 283]}, {class: car, rect: [568, 214, 622, 283]}, {class: car, rect: [743, 186, 822, 300]}, {class: car, rect: [110, 199, 128, 240]}, {class: car, rect: [134, 200, 152, 240]}, {class: car, rect: [158, 200, 176, 240]}, {class: car, rect: [182, 200, 200, 240]}, {class: car, rect: [206, 200, 224, 240]}; ... Repeat until exceeds the max output length.

## B. Model Details

### B.1. Implementation Details of UPN

In alignment with the methodology of T-Rex2 [29], we employ the Swin Transformer Large model [55], pre-trained on ImageNet [19], as the vision backbone. During the Hungarian matching process, the optimization incorporates three types of losses: classification loss, box L1 loss, and generalized intersection over union (GIOU) loss [72], with respective weights of 2.0, 5.0, and 2.0. For the overall loss computation, we similarly utilize classification loss, box L1 loss, and GIOU loss, adjusting the corresponding weights to 1.0, 5.0, and 2.0. Consistent with the training strategy of DINO [102], we adopt contrastive denoising training (CDN) to enhance training stability and accelerate convergence. The pre-trained weights of T-Rex2-L are used for initialization, followed by full-parameter optimization on the universal proposal task.

### B.2. Implementation Details for ChatRex

We utilize the CLIP pre-trained ViT-Large-14-336 model as the low-resolution visual encoder and the LAION pretrained ConvNext-Large-320 model as the high-resolution visual encoder. The input resolution is set to 336x336 for the low-resolution encoder and 768x768 for the high-resolution encoder. During the pretraining stage, we employ a batch size of 32 per device, resulting in an aggregate batch size of 256 across all devices. For the instruction-tuning stage, the batch size is reduced to 16 per device, with a total batch size of 128. The learning rate is initialized at 1e-3 for the pre-training stage and adjusted to 2e-5 during the instruction-tuning stage.

For perception and region-based question-answering tasks, we designed tailored prompts to effectively guide and instruct the models. Examples of these customized prompts

![](images/c4c46a9cdafb82b2d0ed916a61d2456b281939485dfb25b2ef6d535d9f887dc6.jpg)  
Figure 5. Visualized prediction results on the COCO dataset, from general-purpose MLLM including Qwen2-VL [85], InternVL2 [14], and detection-focused MLLMs including Ferret [94], Shikra [10], and Groma [61] These models generally suffer from a low recall rate in multi-object scenes.

<table><tr><td>Method</td><td>Prompt</td></tr><tr><td>Qwen2-VL-7B &amp; InternVL2-8B</td><td>In this picture, you are required to finish object detection for every instance of the category we provide. To complete the above mission, you need to provide me with the answers in the format of a Python list of dictionaries by the category provided above. Attention: No other category shall appear in the detection object attributes, except for the genre we offer. Bounding box format: [108(xmin), 210(ymin), 810(xmax), 640(ymax)], where xmin, ymin, xmax and ymax must be positive integers. If there is no object in the picture, please provide an empty list. Here is an example which you must follow in your responses. Example: If the question is as below: Category: [&#x27;person&#x27;, &#x27;car&#x27;]. If there is an object of the category, The Answer should be: {{{&quot;class&quot;: &quot;person&quot;, &quot;rect&quot;: [0, 614, 220, 771]}}}, {{{&quot;class&quot;: &quot;person&quot;, &quot;rect&quot;: [638, 468, 784, 941]}}}, {{{&quot;class&quot;: &quot;car&quot;, &quot;rect&quot;: [110, 100, 500, 300]}}}}. Else if no object of the category in the picture, the Answer should be: {}. Here is the question you shall answer: Category: {}</td></tr><tr><td>Ferret-7B</td><td>What is the location of all instances of categories {} in the image? Please answer me respectively.</td></tr><tr><td>Shikra-7B</td><td>Help me locate {}. in &lt;image&gt;and give its coordinates, please.</td></tr><tr><td>Groma-7B</td><td>[grounding] There are categories you need to describe with positions, only including &lt;p&gt; {}. Give me a short description of the image and include the coordinates [[x0,y0,x1,y1]] for each instance of categories.</td></tr></table>

Table 8. Prompt used by each MLLM for object detection.

are provided in Tab. 9.

## C. Details for the Rexverse-2M Data Engine

### C.1. Visualization of Rexverse-2M dataset

We visualize a portion of the Rexverse-2M dataset in Fig. 6, including image-level annotations and region-level annotations.

### C.2. Prompt for Different Modules

In the Rexverse-2M data engine, we leverage both state-of-the-art MLLMs and Large Language Models LLMs to construct the dataset. The prompts employed in each module are detailed in Tab. 10.

### C.3. Effectiveness of Phrase-Conditioned Region Description

In the data engine, to generate region-level descriptions, we adopt a phrase-conditioned region captioning method. This approach utilizes a short phrase or category name, specified for each region during the grounding phase, as an additional prompt to guide a multimodal large language model (MLLM) in producing captions. This method differs from directly inputting regional images into the MLLM for captioning. As illustrated in Figure 7, the direct image captioning approach often suffers from hallucinations, particularly when regions contain distracting objects or are too small to be reliably recognized. In contrast, the phrase-conditioned method mitigates these issues by incorporating contextual input, leading to more accurate captions.

<table><tr><td>Task</td><td>Prompt Templates</td></tr><tr><td>Grounding &amp; Detection &amp; Referring 
Brief Image Caption with Grounding 
Detailed Image Caption with Grounding 
Region Caption in Category Name 
Region Caption in Short Phrase 
Region Caption Briefly 
Region Caption in One Sentence 
Grounded Counting 
Grounded Conversation</td><td>Please detect [OBJ] in this image. Answer the question with object indexes. 
Please briefly describe this image and detect all the mentioned objects. Answer with grounded object indexes. 
Please provide a detailed description of the image and detect all the mentioned objects. Answer the question with grounded object indexes. 
What is the category name of [OBJ]? Answer the question with its category name in free format. 
Can you provide me with a short phrase description of [OBJ]? Answer the question with short phrases. 
Can you provide me with a brief description of [OBJ]? Answer the question with brief description. 
Can you provide a one sentence description of [OBJ] in the image? Answer the question with one sentence description. 
How many [OBJ] are there in this image? Answer the question with the number of objects and locate them with object indexes. 
Answer the question in grounded format. Question:</td></tr></table>

Table 9. Example prompt for different perception tasks of ChatRex.  

<table><tr><td>Task</td><td>Model</td><td>Prompt</td></tr><tr><td>Image Description</td><td>InternVL2-8B</td><td>Please provide a one-sentence description for this image.</td></tr><tr><td>Phrase-Conditioned Region Description</td><td>InternVL2-8B</td><td>I will provide you with a short phrase description of an object and its image. You need to rewrite this short phrase description to a one sentence description by adding more details about this object based on the image. The rewritten description can only focus on this object according to the original description and should also be a one-sentence description. The original short phrase description is:</td></tr><tr><td>Region Filtering &amp; Rewriting</td><td>LLAMA3-8B-Instruct</td><td>I will provide you with a one-sentence description of an object, and the category name of that object. Based on these two pieces of information, write a referring description of the object. This description should capture the most important and distinguishing features of the object, and should not describe anything that doesn&#x27;t exist in the description I&#x27;ve provided. Note that the referring object should be the category name provided. The rewritten referring description should be more than 5 words but less than 10 words. The referring description should be as short and concise as possible, without commas. Directly output the answer.</td></tr></table>

Table 10. Prompt for each module where MLLM or LLM is used.

## D. ChatRex Capabilities and Qualitative Examples

In this section, we present the visualization results to demonstrate the capabilities of ChatRex.

### D.1. Common Object Detection

We show the results on the common object detection task in Fig. 8.

### D.2. Long-tailed Object Detection

We show the results on the long-tailed object detection task in Fig. 9.

### D.3. Short-Phrase Object Detection

We show the results on the short-phrase object detection task in Fig. 10.

### D.4. Referring Object Detection

We show the results on the referring object detection task in Fig. 11.

### D.5. Region Caption

We show the results on the region caption task in Fig. 12.

### D.6. Region QA

We show the results on the region QA task in Fig. 13.

### D.7. Brief Grounded Image Caption

We show the results on the brief grounded image caption task in Fig. 14.

### D.8. Detailed Grounded Image Caption

We show the results on the detailed grounded image caption task in Fig. 15.

### D.9. Grounded Counting

We show the results on the grounded counting task in Fig. 16.

### D.10. Grounded Conversation

We show the results on the grounded conversation task in Fig. 17 and Fig. 18.

## Image Caption & Region Grounding

![](images/6c9a0d1186b10bd63de9a1c369115d737862152c71275809c1578308afab64a0.jpg)

The image features a unique combination of objects: a green, semi-precious stone ring with a polished and faceted surface, resting on a large, irregularly shaped, clear crystal rock, surrounded by various other colorful gemstones and moss in the background, creating a visually appealing and intricate display

![](images/23ac3e6a84226a4177080495510c0ad3d8352cbb59bce61ba1d0d02ec07ed4cf.jpg)

A high-speed Formula 1 race car, number 12, adorned with Verizon and Shell logos, navigates a turn on a green track with blurred spectators in the background, captured in motion by the sharp focus on the car.

![](images/c75463b6472f15559f8095fe8eaf71275bc5d9339c15075008ddd16e9afbc5a4.jpg)

The image shows a sleek black Mini Cooper S car with the license plate "S.SB 2069" in motion on a road, featuring modern design elements such as a prominent front grille, angular headlights, and aerodynamic contours, captured with a motion blur effect to emphasize speed and dynamism against a backdrop of blurred trees and a clear sky.

![](images/102398861707d1eb7ce2b268586c59d3a3bc17185ae6301ed954986c5bcc27c1.jpg)

![](images/891141e001f23526769df4c75dcdc4cbccda9977785c2003cd9ca9049e78ff3e.jpg)

Three white horses are galloping through a body of water creating splashes and sprays, against a dramatic, sepia-toned sky.

The image captures two young girls deeply engrossed in playing violins, their focused expressions reflecting their dedication to the music, with their hands expertly positioned on the instruments and bows in motion, while seated in a classroom setting with a blurred background featuring other students and a conductor.

![](images/6029725dc51b0ea3a36c170527d588b105143e34f8ff66a616dc91d367f026bb.jpg)

Three scuba divers are posing for a photo on a boat, wearing black wetsuits with "Aventura" logos, yellow snorkels, and snorkel masks, with the ocean and clear blue sky in the background

### Region Caption

![](images/cd679bdc5185ebb6571a73eac1e0174f32f89991bedc96d660f9940547d38033.jpg)

Detailed Caption: A white paper cup with a green polka dot pattern, labeled "Fall Style Autumn Collection" and featuring a steaming cup icon with "Tea House" branding, accompanied by a tea leaf.

Referring Caption: White paper cup with green polka dots.

![](images/c4b3c5e2cb2a154f04efc12b1ed47ad7c1a2c9274c3c993b216d0019d5a7f6f5.jpg)

Detailed Caption: A vibrant, blue-tinged mushroom stands prominently against a blurred backdrop of lush greenery and warm sunlight filtering through the foliage.

Referring Caption: Vibrant blue-tinged mushroom stands prominently against greenery.

![](images/3f2c8481438bdcfaffd58c1a60c90a2edbd414aec10f18dcc5ce1b7c64f3adb6.jpg)

Detailed Caption: A colorful bracelet featuring a mix of pastel and metallic beads, showcasing a combination of green, pink, silver, and black tones.

Referring Caption: Colorful mix of pastel and metallic beads in green pink silver black

![](images/395f1d163f47e9d759fac31d288f11cbcb83530b481105113e2f143f654ae82d.jpg)

Detailed Caption: a person's muscular shoulder, highlighting the contours and definition of the upper arm muscles.

Referring Caption: Muscular upper arm with defined contours.

![](images/41c61618ecb1d233089362ba89daa6721c1244ef6e404e5dd810196726a71362.jpg)  
Figure 6. Visualization of the Rexverse-2M dataset.

Detailed Caption: A vibrant green spring of mint delicately adorns a slice of toasted garlic bread, adding a fresh burst of flavor.

Referring Caption: Fresh green mint leaf on toasted garlic bread.

![](images/b48700e27c49388ace215a008db5d7fe1b4b599929f17b5f5588c3315acc1cac.jpg)

Detailed Caption: a car trunk, featuring a gray carpeted floor and a neatly arranged space designed for storage

Referring Caption: Gray carpeted storage space for luggage and cargo.

![](images/a60b98f5d93f25bc6f677f99debea7509265ca07a1f7e172a51a195da5b877bf.jpg)  
Figure 7. Visualization of the proposed phrase-conditioned region description method.

#### Category Name: top

With Phrase-Conditioned: a V-neckline top adorned with a delicate necklace featuring a circular pendant.

Without Phrase-Conditioned: a close-up of a person wearing a burgundy-colored top and a delicate necklace with a pendant.

![](images/832c95851e9598ea7c0b3f9a06ff5bb78c2b4a9093f633718548cdb011adfeee.jpg)

#### Category Name: top

With Phrase-Conditioned: a dark suit jacket with a white shirt underneath is prominently displayed in the image

Without Phrase-Conditioned: a person wearing a black suit with a white shirt underneath.

![](images/ef4b5fd133dd8b921d48ace0617043befbd6f7a58005322fadeb11e62c310ff2.jpg)

![](images/952a04fdd210114d36c9902a74d3d114019ad837f53fe1e7d479ce847e5b0564.jpg)

![](images/879be1451878fa5bd2b83ec958584cbb84f7a1cda634d6ef3243476b01abf9e3.jpg)

![](images/6176f7a6fd496ce58b357377ca5ec54e12d061435e04fd4c3c883f2712e9ffa6.jpg)

![](images/1474c4f57f34237190837e5d9a11a3291c42f77c8b8572861a22bdd87fd10a12.jpg)

![](images/b114d8b4131671c97480df561d3d195b5aee2649426edfba9f6be05dba412990.jpg)

![](images/3004537141dc61e84f2409730ae448c58727112cadfc6c012c0f74345fa8d6c5.jpg)

![](images/15c01bee3c5b8732bfe1a9dd571c1a17c453556249d37802f2c9df3014b090d8.jpg)

![](images/10102497083f11b3331e6eb69a9b8d9d4fae4c5629939575eae4a3a54f7c30b4.jpg)

![](images/2b2dbf352a86ac8f57c411356e68ae81bd76d54003c2ca0823a02f151a912a39.jpg)

![](images/9a043a72cf3b5148080606de8f7165797a087bc515ad8b2dce21f0db2dd7067b.jpg)  
Figure 8. Visualization on the Common Object Detection Task.

![](images/870fba0a934157d9ed51572ef0aed4d0c08f592edd1b97be514fc9918d90bb81.jpg)

![](images/e0323280b931ac309c22d1f210299df6c4468c541a1d47d5c315c8898e241723.jpg)

![](images/e61774df1be4032ed5d555082e0d7f8cb062a702fe868f543324fe1659ce7f72.jpg)

![](images/ac26676c7ee48ac1adfd69c48662f3b94bf00004559bc1e5a9645e903b19b4ec.jpg)

![](images/02dca2e9536166f092d4c75d7ed291e2b8907736d78db184501cc5d1b3de2f28.jpg)

![](images/34b9ed98661f6d4bb57e3e0a37415063b6a310eaf91eccabd80ac2cde64ca768.jpg)

![](images/139df3a39a43d6f032ce20fcef8ba3e7fed094e6aa3ca2f643e12a0e60b8d546.jpg)

![](images/2ed10329a186cc9a5a76796ff63ec5f295bed0f75a1aa8a06b34d0c5f5b7e730.jpg)

![](images/dfb8476d967ae1af1321092a9f1dbd2232f068c3622adeec634b9dd35a5defc4.jpg)

![](images/70d79809914ca8bfe5532b9b895c4b19fd1ffc66d18dcf5ce1b6982aa81a8be9.jpg)

![](images/b2cfc17bd41d3fc2d2912905cea70f04a1e436ea91fc398db1d98b1a180deda5.jpg)

![](images/0ebd9e860aadd7c36ed4abbffe09cc1f1404115e1f1ea5ffa5208784f6694cb9.jpg)

![](images/cbd4b6c23df5df25bfe02fd615d414cc41133f30da94a593cbb1594d37d76755.jpg)  
Figure 9. Visualization on the Long-tailed Object Detection Task.

![](images/a623fd59968ba0e0984c466b7d99f33dac7364fd472f9005cac8fcf10334e3aa.jpg)

![](images/5c654108312aa2a88dec3d6b801f39abbc62279a9eada2c460319df5c93e975a.jpg)

![](images/1a74103dd0770cb6d66adec8f969112f1a37f25551207f4caa967c24faad0b9d.jpg)

![](images/42f376a105cca31ef2fe1babc17f505228e10f7fd4626ba5760cbb7c12d6a60a.jpg)

![](images/bfbdf87084d6860a4f86060c0cd54f0a2e71d45658e8179404d3a3876dcc1058.jpg)

![](images/99d0a79758e48bb1cb690b758cedaa4c639d9827d2a4a41f634b617da4f47935.jpg)

![](images/57e5089bdbe913a803a36131a5bdf2ff28524c886d29b107a92cec6e99e42068.jpg)

![](images/9bbcb70f37bed581741b0cfc679b248a0685615bb390b06b32fb837d81623e7f.jpg)

![](images/61abcc0e60ba22a0991ad08a9f6a9c8c5a0ed16dca8555e88f41589b8a508d9c.jpg)

![](images/c00711fefd3b81474337b8106357d1255bef20d00147270a375ecd5898fe2f5e.jpg)

![](images/445b906d189b0ff84c2bca8ed6d8dd200243a8525b1792e9c83428f0547838c8.jpg)

![](images/49fbe5afbb34b528136f90a397f30dc6742245f6cc8c8947b07cd68f246b5e6f.jpg)  
Figure 10. Visualization on the Short-Phrase Object Detection Task.

![](images/2cbdda60aa6c50e02ad5e318175d69aaaa4357c7f1e0a552e440b74d7bceb068.jpg)

![](images/825dc42f5bdab5516495d75d87bc9cb3c6e410c30d6619fa2438620a3441d137.jpg)